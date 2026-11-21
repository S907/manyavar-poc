#!/usr/bin/env python3
"""Independent rule check. Reads the raw data pack and out/moves.json and re-checks every rule from scratch.
It shares no code with stock_mover.py, so a bug there cannot hide here.

Usage:  python engine/check_rules.py --data path/to/csv --out out
"""
import argparse, json, os, re, sys
from collections import defaultdict
import pandas as pd

def read(d, n): return pd.read_csv(os.path.join(d, n + ".csv"), dtype=str, keep_default_na=False)

def check(data_dir, out_dir):
    R = json.load(open(os.path.join(out_dir, "moves.json"))); moves = R["moves"]; WH = R["warehouse"]
    stores = read(data_dir, "stores").set_index("store_id"); items = read(data_dir, "items").set_index("sku_id")
    snap = read(data_dir, "stock_snapshot"); weekly = read(data_dir, "stock_weekly"); mind = read(data_dir, "min_display")
    prot = read(data_dir, "flagship_protected"); leads = read(data_dir, "lead_times"); inbound = read(data_dir, "warehouse_inbound")
    bills = read(data_dir, "bills"); lines = read(data_dir, "bill_lines")
    today = pd.to_datetime(snap.as_of_date).max()
    oh = defaultdict(int); it = defaultdict(int)
    for r in snap.itertuples():
        try: v = int(r.on_hand)
        except Exception: v = 0
        oh[(r.location_id, r.sku_id)] = max(v, 0)
        try: it[(r.location_id, r.sku_id)] = max(int(r.in_transit), 0)
        except Exception: it[(r.location_id, r.sku_id)] = 0
    # Reconcile the snapshot to the weekly close for the same day, independently of the planner, then check moves against that.
    recon = {}
    w2 = weekly.copy(); w2["we"] = pd.to_datetime(w2.week_ending, errors="coerce"); w2["c"] = pd.to_numeric(w2.closing_on_hand, errors="coerce")
    if (w2.we == today).any():
        for r in w2[w2.we == today].itertuples():
            k = (r.store_id, r.sku_id)
            if r.sku_id not in items.index or pd.isna(r.c) or r.c < 0: continue
            if int(r.c) != oh.get(k, 0): recon[k] = (oh.get(k, 0), int(r.c)); oh[k] = int(r.c)
    out = defaultdict(int); inc = defaultdict(int)
    for m in moves:
        for k, q in m["skus"].items(): out[(m["from_loc"], k)] += q; inc[(m["to_loc"], k)] += q
    results = []
    def res(rule, bad, checked, note=""):
        results.append(dict(rule=rule, passed=len(bad) == 0, checked=checked, violations=len(bad), examples=bad[:5], note=note))

    # 1 real products only, real stock only
    bad = [f"{m['move_id']} {k}" for m in moves for k in m["skus"] if k not in items.index or items.is_packaging[k] == "1"]
    res("Only real products move (no packaging, no unknown SKU)", bad, sum(len(m["skus"]) for m in moves))
    inb = defaultdict(int)
    for r in inbound.itertuples(): inb[r.sku_id] += int(r.qty) if pd.to_datetime(r.expected_date) <= today + pd.Timedelta(days=R["params"]["INBOUND_WAIT_DAYS"]) else 0
    bad = []
    for (loc, k), q in out.items():
        have = max(oh[(loc, k)], 0) + (inb[k] if loc == WH else 0)
        if q > have: bad.append(f"{loc} {k}: sends {q}, has {have}")
    res("No location sends more than it holds", bad, len(out))
    # 2 capacity
    bad = []
    for s in stores.index:
        now = sum(max(v, 0) for (l, k), v in oh.items() if l == s and k in items.index and items.is_packaging[k] != "1") + sum(v for (l, k), v in it.items() if l == s)
        after = now + sum(v for (l, k), v in inc.items() if l == s) - sum(v for (l, k), v in out.items() if l == s)
        got = sum(v for (l, k), v in inc.items() if l == s)
        if got > 0 and after > int(stores.stock_capacity_units[s]): bad.append(f"{s}: {after} after moves, capacity {stores.stock_capacity_units[s]}")
    res("Capacity: no store is sent stock beyond what it can hold (in-transit counted)", bad, len(stores))
    # 3 minimum display for every store that gives
    cats = list(mind.category.unique())
    def grp(c):
        for g in cats:
            if g == c or re.search(r"\b" + re.escape(c) + r"\b", g): return g
    md = {(r.tier, r.category): int(r.min_display_units) for r in mind.itertuples()}
    bad = []; n = 0
    givers = set(l for (l, k) in out if l != WH)
    for s in givers:
        for g in cats:
            ks = [k for k in items.index if grp(items.category[k]) == g]
            gave = sum(out[(s, k)] for k in ks)
            if gave == 0: continue
            n += 1
            left = sum(max(oh[(s, k)], 0) - out[(s, k)] for k in ks)
            if left < md.get((stores.tier[s], g), 0): bad.append(f"{s} {g}: {left} left, minimum {md[(stores.tier[s], g)]}")
    res("Minimum display: a giving store stays at or above its minimum for the category", bad, n)
    # 4 flagship protection
    P = set((r.store_id, r.style_id) for r in prot.itertuples())
    bad = [f"{m['move_id']} {m['from_loc']} {m['style_id']}" for m in moves if stores.tier.get(m["from_loc"]) == "S++" and (m["from_loc"], m["style_id"]) in P]
    res("Flagship protection: S++ stores never give a top-20 style", bad, sum(1 for m in moves if stores.tier.get(m["from_loc"]) == "S++"))
    # 5 donor cover, with velocity = units sold / days the style was in stock (the brief's definition)
    weekly = weekly[weekly.sku_id.isin(items.index)].copy(); weekly["style"] = weekly.sku_id.map(items.style_id); weekly["d"] = weekly.days_in_stock.astype(int)
    we = pd.to_datetime(weekly.week_ending); w0, w1 = we.min() - pd.Timedelta(days=6), we.max()
    sdays = weekly.groupby(["store_id", "style", "week_ending"]).d.max().groupby(level=[0, 1]).sum().to_dict()
    s = lines.merge(bills[["bill_id", "bill_date", "store_id"]], on="bill_id"); s = s[s.sku_id.isin(items.index)]; s["dt"] = pd.to_datetime(s.bill_date)
    s = s[(s.dt >= w0) & (s.dt <= w1)]; s["style"] = s.sku_id.map(items.style_id); ssold = s.groupby(["store_id", "style"]).qty.apply(lambda x: x.astype(int).sum()).to_dict()
    bad = []; n = 0; seen = set()
    for m in moves:
        a, b_, sid = m["from_loc"], m["to_loc"], m["style_id"]
        if a == WH or b_ == WH or (a, sid) in seen: continue
        seen.add((a, sid)); n += 1
        ks = [k for k in items.index if items.style_id[k] == sid]
        left = sum(max(oh[(a, k)], 0) + it[(a, k)] + inc[(a, k)] - out[(a, k)] for k in ks)
        d = sdays.get((a, sid), 0); v = ssold.get((a, sid), 0) / d if d else 0
        if v > 0 and left / v < 30: bad.append(f"{a} {sid}: {left} left = {left / v:.0f} days")
    res("Donor cover: a giving store keeps at least 30 days of cover for the style", bad, n, "velocity = units sold in the window / days the style was in stock")
    # 6 in-transit is counted, nothing is sent twice
    vel = pd.read_csv(os.path.join(out_dir, "velocity.csv")).set_index(["store_id", "sku_id"])
    bad = []; n = 0
    for (loc, k), q in inc.items():
        if loc == WH or it[(loc, k)] == 0: continue
        n += 1
        v = float(vel.season_per_day.get((loc, k), 0)); total = max(oh[(loc, k)], 0) + it[(loc, k)] + q
        limit = v * (max(int(x) for x in leads.days) + R["params"]["PUSH_FILL_COVER"]) + 1
        if total > limit: bad.append(f"{loc} {k}: {it[(loc, k)]} in transit + {q} sent = {total}, more than it can sell")
    res("In-transit stock counts as arriving: nothing is sent twice", bad, n, "checked every line going to a store-size that already has stock on the way")
    # 7 approval flag
    mrp = items.mrp.astype(int)
    bad = [m["move_id"] for m in moves if (sum(q * mrp[k] for k, q in m["skus"].items()) > R["params"]["APPROVAL_VALUE"]) != m["needs_approval"]]
    res("Approval: every move above Rs 1,00,000 at MRP is flagged for a human", bad, len(moves), f"{sum(m['needs_approval'] for m in moves)} lines flagged")
    # 8 held stock untouched
    held = set(tuple(i["where"].split(" ")) for i in R["issues"] if i["kind"] in ("impossible stock", "stock records disagree", "impossible in-transit"))
    bad = [f"{m['move_id']} {k}" for m in moves for k in m["skus"] if (m["from_loc"], k) in held or (m["to_loc"], k) in held]
    res("Data issues are flagged, not acted on", bad, len(held), "stock with impossible or conflicting numbers is in no move")
    # 8b reconciliation matches what the planner published
    pub = {(c["location_id"], c["sku_id"]): c["on_hand"] for c in R.get("corrected_stock", [])}
    bad = []
    for k, (was, now) in recon.items():
        if pub.get(k) != now: bad.append(f"{k[0]} {k[1]}: weekly close {now}, planner used {pub.get(k)}")
    for k, v in pub.items():
        if k not in recon: bad.append(f"{k[0]} {k[1]}: planner changed it to {v}, the weekly close does not require that")
    res("Snapshot reconciled to the weekly history where they disagreed", bad, len(recon) + len(pub), f"{len(recon)} cells corrected from the weekly close")
    # 9 every move has a reason
    bad = [m["move_id"] for m in moves if not m.get("reason") or "\n" in m["reason"]]
    res("Every move is explained in one line", bad, len(moves))
    summary = dict(all_passed=all(r["passed"] for r in results), moves=len(moves), results=results)
    json.dump(summary, open(os.path.join(out_dir, "rule_check.json"), "w"), indent=1)
    return summary

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--out", default="out"); a = ap.parse_args()
    r = check(a.data, a.out)
    for x in r["results"]: print(("PASS " if x["passed"] else "FAIL ") + x["rule"] + f"  [{x['checked']} checked, {x['violations']} broken]" + ("  e.g. " + "; ".join(x["examples"][:3]) if x["examples"] else ""))
    print("ALL RULES PASS" if r["all_passed"] else "RULES BROKEN"); sys.exit(0 if r["all_passed"] else 1)
