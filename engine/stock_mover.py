#!/usr/bin/env python3
"""Stock Mover engine. Reads the Manyavar CSV pack, writes a ready-to-approve move list.

Usage:  python engine/stock_mover.py --data path/to/csv --out out
Nothing here is tied to store names, dates or styles: "today" is the snapshot date in the
data, and every rule is read from the rule files, so a new data pack with the same columns runs as is.
"""
import argparse, json, math, os, re, sys
from collections import defaultdict
import numpy as np
import pandas as pd

P = dict(
    PRIOR_DAYS=14,        # weight (in days) of the peer estimate when a SKU has little in-stock history
    TARGET_COVER=21,      # days of cover a top-up aims for, counted after the stock arrives
    TRIGGER_COVER=10,     # top up when cover would fall below lead time + this
    DONOR_MIN_COVER=30,   # rule: a giving store keeps at least this many days of cover for the style
    AGE_DAYS=180,         # stock older than this is "ageing"
    EXCESS_COVER=120,     # cover above this is excess that can move
    PUSH_FILL_COVER=45,   # an ageing/excess push fills a receiving store up to this cover
    DEAD_AGE_DAYS=365,    # no sales anywhere and older than this: pull back
    INBOUND_WAIT_DAYS=7,  # wait for a warehouse delivery due within this many days before raiding a store
    APPROVAL_VALUE=100000,
    MIN_PUSH_UNITS=3,     # store-to-store pushes only for a real pile, not single pieces
    FORWARD_DAYS=45,      # how far ahead the demand forecast looks
    FACTOR_CLIP=(0.6, 2.5),   # the season model is tested up to about 1.4x; beyond 2.5x we do not trust it
)

REQUIRED = {
    "stores": ["store_id", "city", "state", "zone", "tier", "stock_capacity_units"],
    "items": ["sku_id", "style_id", "style_name", "category", "size", "mrp", "is_packaging"],
    "stock_snapshot": ["as_of_date", "location_id", "sku_id", "on_hand", "in_transit"],
    "stock_weekly": ["week_ending", "store_id", "sku_id", "closing_on_hand", "days_in_stock"],
    "bills": ["bill_id", "bill_date", "store_id"],
    "bill_lines": ["bill_id", "sku_id", "qty"],
    "calendar": ["date", "state", "festival", "is_wedding_date"],
    "warehouse_inbound": ["expected_date", "sku_id", "qty"],
    "min_display": ["tier", "category", "min_display_units"],
    "lead_times": ["route", "days"],
    "flagship_protected": ["store_id", "style_id"],
    "rules": ["rule", "detail"],
    "area_managers": ["area_manager_id", "name", "stores"],
}
OPTIONAL_TABLES = {"calendar", "warehouse_inbound", "flagship_protected", "rules", "min_display", "lead_times", "area_managers"}   # missing -> warned, run continues
OPTIONAL_COLS = {("stores", "opened_on"), ("items", "launch_date"), ("stock_snapshot", "in_transit_arrives_on"), ("stock_snapshot", "oldest_stock_received_on")}

class DataError(Exception):
    pass

class Pack:
    """The data pack: a folder of CSVs, or the Excel workbook (a .xlsx path, or a folder holding one)."""
    def __init__(self, path):
        self.path = path; self.book = None; self.warnings = []
        x = path if os.path.isfile(path) and path.lower().endswith((".xlsx", ".xlsm")) else None
        if x is None and os.path.isdir(path) and not os.path.exists(os.path.join(path, "stock_snapshot.csv")):
            xs = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.lower().endswith(".xlsx")]
            x = xs[0] if xs else None
        if x:
            self.book = {str(k).strip().lower(): v for k, v in pd.read_excel(x, sheet_name=None, dtype=str, keep_default_na=False).items()}
        elif not os.path.isdir(path):
            raise DataError(f"Data not found: {path}. Give a folder of CSV files or the .xlsx workbook.")
    def read(self, name):
        if self.book is not None: df = self.book.get(name)
        else:
            fp = os.path.join(self.path, name + ".csv")
            df = pd.read_csv(fp, dtype=str, keep_default_na=False) if os.path.exists(fp) else None
        need = REQUIRED[name]
        if df is None:
            if name in OPTIONAL_TABLES:
                self.warnings.append((name, "table is missing; the run continues without it")); return pd.DataFrame(columns=need + [c for (t, c) in OPTIONAL_COLS if t == name])
            raise DataError(f"Required table '{name}' is missing from {self.path}.")
        df = df.copy(); df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        for c in df.columns: df[c] = df[c].astype(str).str.strip().replace({"nan": "", "NaT": "", "None": ""})
        miss = [c for c in need if c not in df.columns]
        if miss: raise DataError(f"Table '{name}' is missing column(s): {', '.join(miss)}. Found: {', '.join(df.columns)}.")
        for (t, c) in OPTIONAL_COLS:
            if t == name and c not in df.columns: df[c] = ""; self.warnings.append((name, f"column {c} is missing; treated as blank"))
        for c in df.columns:
            if c.endswith("_date") or c.endswith("_on") or c in ("date", "week_ending"): df[c] = df[c].str.slice(0, 10)   # Excel adds a time part
        return df

def rule_number(rules, word, default, pattern):
    """Read a number out of the rule text, e.g. '30 days' or 'Rs 1,00,000'. Falls back to the default."""
    for r in rules.itertuples():
        if word in str(r.rule).lower():
            m = re.search(pattern, str(r.detail))
            if m:
                try: return int(m.group(1).replace(",", "")), True
                except ValueError: pass
    return default, False

def to_int(s):
    return pd.to_numeric(s, errors="coerce")

def poisson_fit(X, y, iters=40, ridge=1e-3):
    b = np.zeros(X.shape[1]); b[0] = math.log(max(y.mean(), 1e-6))
    for _ in range(iters):
        eta = np.clip(X @ b, -20, 20); mu = np.exp(eta)
        z = eta + (y - mu) / mu
        A = X.T @ (X * mu[:, None]) + ridge * np.eye(X.shape[1])
        nb = np.linalg.solve(A, X.T @ (mu * z))
        if np.max(np.abs(nb - b)) < 1e-7: b = nb; break
        b = nb
    return b

def run(data_dir, out_dir, params=None):
    p = dict(P); p.update(params or {})
    issues = []          # data problems: flagged, never acted on
    def issue(kind, where, detail): issues.append(dict(kind=kind, where=where, detail=detail))

    pack = Pack(data_dir); read = pack.read
    stores = read("stores"); items = read("items")
    snap = read("stock_snapshot"); weekly = read("stock_weekly")
    bills = read("bills"); lines = read("bill_lines")
    cal = read("calendar"); inbound = read("warehouse_inbound")
    mind = read("min_display"); leads = read("lead_times")
    prot = read("flagship_protected"); rules = read("rules"); amgr = read("area_managers")
    for t, w in pack.warnings: issue("data pack", t, w)
    # the numbers in the rules come from the rules file, so a changed rule changes the run
    if "DONOR_MIN_COVER" not in (params or {}):
        p["DONOR_MIN_COVER"], ok = rule_number(rules, "cover", p["DONOR_MIN_COVER"], r"(\d+)\s*days")
        if not ok: issue("rules", "Donor cover", f"could not read the number of days from the rules; using {p['DONOR_MIN_COVER']}")
    if "APPROVAL_VALUE" not in (params or {}):
        p["APPROVAL_VALUE"], ok = rule_number(rules, "approval", p["APPROVAL_VALUE"], r"Rs\.?\s*([\d,]+)")
        if not ok: issue("rules", "Approval", f"could not read the rupee limit from the rules; using {p['APPROVAL_VALUE']}")
    for df, name, col in [(stores, "stores", "store_id"), (items, "items", "sku_id")]:
        d = df[df[col].duplicated()][col].unique()
        if len(d): issue("duplicate rows", name, f"{len(d)} repeated {col}(s), e.g. {d[0]}; the first row is used")
    stores = stores.drop_duplicates("store_id"); items = items.drop_duplicates("sku_id")
    stores["stock_capacity_units"] = to_int(stores.stock_capacity_units)
    for r in stores[stores.stock_capacity_units.isna()].itertuples(): issue("no capacity", r.store_id, "stock_capacity_units is blank or not a number; nothing is sent to this store")
    stores["stock_capacity_units"] = stores.stock_capacity_units.fillna(0).astype(int).astype(str)
    dsn = snap[snap.duplicated(["location_id", "sku_id"], keep="last")]
    if len(dsn): issue("duplicate rows", "stock_snapshot", f"{len(dsn)} location and SKU pairs appear more than once, e.g. {dsn.iloc[0].location_id} {dsn.iloc[0].sku_id}; the last row is used")
    snap = snap.drop_duplicates(["location_id", "sku_id"], keep="last")
    if snap.empty or pd.to_datetime(snap.as_of_date, errors="coerce").isna().all(): raise DataError("stock_snapshot has no usable as_of_date, so there is no 'today' to plan for.")
    unk = sorted(set(snap.sku_id) - set(items.sku_id))
    if unk: issue("unknown SKU", "stock_snapshot", f"{len(unk)} SKU(s) not in items, e.g. {unk[0]}; ignored")

    today = pd.to_datetime(snap.as_of_date, errors="coerce").max()
    store_ids = list(stores.store_id)
    S = stores.set_index("store_id")
    cap = to_int(S.stock_capacity_units).to_dict()
    tier = S.tier.to_dict(); zone = S.zone.to_dict(); city = S.city.to_dict(); state = S.state.to_dict()
    opened = pd.to_datetime(S.opened_on, errors="coerce").to_dict()
    weekly = weekly[weekly.store_id.isin(store_ids)]; bills = bills[bills.store_id.isin(store_ids)]
    prot = prot[prot.store_id.isin(store_ids)]
    wh_ids = sorted(set(snap.location_id) - set(store_ids))
    if len(wh_ids) != 1: issue("warehouse", ",".join(wh_ids) or "none", "expected exactly one location that is not a store; using the first" if wh_ids else "no warehouse stock in the snapshot; only store-to-store moves are possible")
    WH = wh_ids[0] if wh_ids else "WAREHOUSE"
    if len(wh_ids) > 1: snap = snap[~snap.location_id.isin(wh_ids[1:])]

    items["is_pack"] = items.is_packaging == "1"
    prod = items[~items.is_pack].copy()
    I = prod.set_index("sku_id")
    style_of = I.style_id.to_dict(); cat_of = I.category.to_dict(); size_of = I["size"].to_dict()
    mrp = to_int(I.mrp).fillna(0).to_dict(); style_name = prod.drop_duplicates("style_id").set_index("style_id").style_name.to_dict()
    style_cat = prod.drop_duplicates("style_id").set_index("style_id").category.to_dict()
    launch = pd.to_datetime(prod.drop_duplicates("style_id").set_index("style_id").launch_date, errors="coerce").to_dict()
    skus_of_style = prod.groupby("style_id").sku_id.apply(list).to_dict()
    for sid, ld in launch.items():
        if pd.isna(ld): issue("blank launch date", sid, "style has no launch date; treated as an old style")

    # --- minimum display: map each item category to the min_display category that names it
    md_cats = list(mind.category.unique())
    def group_of(cat):
        for g in md_cats:
            if g == cat: return g
        for g in md_cats:
            if re.search(r"\b" + re.escape(cat) + r"\b", g): return g
        return None
    grp = {c: group_of(c) for c in prod.category.unique()}
    for c, g in grp.items():
        if g is None: issue("no minimum display", c, "category has no row in min_display; no minimum applied")
    mind["min_display_units"] = to_int(mind.min_display_units).fillna(0).astype(int)
    min_disp = {(r.tier, r.category): int(r.min_display_units) for r in mind.itertuples()}
    def min_for(store, cat):
        g = grp.get(cat); return min_disp.get((tier[store], g), 0) if g else 0

    # --- lead times: the route is a sentence
    lt = dict(wh={}, same_city=None, same_zone=None, diff_zone=None)
    for r in leads.itertuples():
        t = str(r.route).lower(); d = to_int(pd.Series([r.days])).iloc[0]
        if pd.isna(d): issue("lead time", r.route, "days is not a number; this route falls back to the slowest known time"); continue
        d = int(d)
        if "warehouse" in t:
            for z in set(zone.values()):
                if re.search(r"\b" + z.lower() + r"\b", t): lt["wh"][z] = d
        elif "same city" in t: lt["same_city"] = d
        elif "same zone" in t: lt["same_zone"] = d
        elif "different zone" in t: lt["diff_zone"] = d
    known = [v for v in list(lt["wh"].values()) + [lt["same_city"], lt["same_zone"], lt["diff_zone"]] if v is not None]
    worst = max(known) if known else 7
    def lead(a, b):
        if a == WH or b == WH:
            s = b if a == WH else a
            v = lt["wh"].get(zone[s])
            if v is None: issue("lead time", s, f"no warehouse lead time for zone {zone[s]}; assumed {worst} days"); lt["wh"][zone[s]] = worst; v = worst
            return v
        if city[a] == city[b]: return lt["same_city"] or worst
        if zone[a] == zone[b]: return lt["same_zone"] or worst
        return lt["diff_zone"] or worst

    protected = set((r.store_id, r.style_id) for r in prot.itertuples())

    # --- stock position
    snap["oh"] = to_int(snap.on_hand); snap["it"] = to_int(snap.in_transit)
    snap = snap[snap.sku_id.isin(I.index)].copy()
    on_hand = defaultdict(int); in_transit = defaultdict(int); recv_date = {}; frozen = set(); corrected = {}; neg = []
    for r in snap.itertuples():
        k = (r.location_id, r.sku_id)
        oh = r.oh; it = r.it
        if pd.isna(oh) or oh < 0: neg.append((k, r.on_hand)); oh = 0            # resolved against the weekly close below, if possible
        if pd.isna(it) or it < 0:
            issue("impossible in-transit", f"{r.location_id} {r.sku_id}", f"in_transit is '{r.in_transit}'; treated as 0"); frozen.add(k); it = 0
        on_hand[k] = int(oh); in_transit[k] = int(it)
        d = pd.to_datetime(r.oldest_stock_received_on, errors="coerce")
        if not pd.isna(d): recv_date[k] = d
        elif oh > 0 and r.location_id != WH: issue("blank received date", f"{r.location_id} {r.sku_id}", "stock on hand with no received date; age unknown, not treated as ageing")
    age = {k: (today - d).days for k, d in recv_date.items()}
    # Reconcile from the data, not from any statement: the weekly table closes on the snapshot day too, so where the
    # single snapshot figure disagrees with the 12-week series, use the weekly close and record the correction.
    wk = weekly.copy(); wk["we"] = pd.to_datetime(wk.week_ending, errors="coerce"); wk["c"] = to_int(wk.closing_on_hand)
    done_recon = set()
    if (wk.we == today).any():
        raw_oh = {(r.location_id, r.sku_id): r.on_hand for r in snap.itertuples()}
        for r in wk[wk.we == today].itertuples():
            k = (r.store_id, r.sku_id)
            if r.sku_id not in I.index or r.store_id not in cap or pd.isna(r.c) or r.c < 0: continue
            if int(r.c) != on_hand.get(k, 0):
                issue("snapshot corrected", f"{r.store_id} {r.sku_id}", f"snapshot shows {raw_oh.get(k, 'no row')}, the weekly close for the same day shows {int(r.c)}; used {int(r.c)}. Please recount")
                on_hand[k] = int(r.c); corrected[k] = int(r.c); done_recon.add(k)
    else:
        issue("no cross-check", "stock_weekly", f"no weekly close on the snapshot date {today.date()}, so the snapshot could not be checked against it")
    for k, raw in neg:                                                          # any negative the weekly close did not resolve
        if k not in done_recon: issue("impossible stock", f"{k[0]} {k[1]}", f"on_hand is '{raw}' and no weekly close is available; treated as 0")

    # --- sales in the same window the weekly stock covers
    weekly["dis"] = to_int(weekly.days_in_stock).fillna(0).clip(0, 7)
    weekly = weekly[weekly.sku_id.isin(I.index)]
    w_end = pd.to_datetime(weekly.week_ending)
    win_start = w_end.min() - pd.Timedelta(days=6); win_end = w_end.max(); win_days = (win_end - win_start).days + 1
    lines = lines[lines.sku_id.isin(I.index)].copy(); lines["qty"] = to_int(lines.qty).fillna(0)
    sales = lines.merge(bills[["bill_id", "bill_date", "store_id"]], on="bill_id", how="left")
    sales["d"] = pd.to_datetime(sales.bill_date, errors="coerce")
    bad = sales.d.isna() | ~sales.store_id.isin(store_ids)
    if bad.any(): issue("unusable sales rows", "bill_lines", f"{int(bad.sum())} lines with no valid bill date or store; ignored")
    sales = sales[~bad]
    win = sales[(sales.d >= win_start) & (sales.d <= win_end)]
    sold = win.groupby(["store_id", "sku_id"]).qty.sum().to_dict()
    dis = weekly.groupby(["store_id", "sku_id"]).dis.sum().to_dict()
    weekly = weekly.assign(style_id=weekly.sku_id.map(style_of))
    for k, q in sold.items():
        if q > 0 and dis.get(k, 0) == 0: issue("sales without stock", f"{k[0]} {k[1]}", f"{int(q)} sold in the window but zero in-stock days recorded")

    # --- peer estimate: chain rate of the SKU x how strong this store is in the category
    sk = pd.DataFrame([(s, k, sold.get((s, k), 0), dis.get((s, k), 0)) for (s, k) in set(sold) | set(dis)], columns=["store", "sku", "sold", "dis"])
    sk["cat"] = sk.sku.map(cat_of)
    chain = sk.groupby("sku")[["sold", "dis"]].sum(); chain_rate = (chain.sold / chain.dis.replace(0, np.nan)).fillna(0).to_dict()
    ccat = sk.groupby("cat")[["sold", "dis"]].sum(); ccat_rate = (ccat.sold / ccat.dis.replace(0, np.nan))
    sc = sk.groupby(["store", "cat"])[["sold", "dis"]].sum().reset_index()
    sc["raw"] = (sc.sold / sc.dis.replace(0, np.nan)) / sc.cat.map(ccat_rate)
    sc["tier"] = sc.store.map(tier)
    tier_idx = sc.groupby(["tier", "cat"]).raw.median().to_dict()
    N0 = 300
    store_idx = {}
    for r in sc.itertuples():
        t = tier_idx.get((r.tier, r.cat)); t = 1.0 if t is None or pd.isna(t) else t
        raw = t if pd.isna(r.raw) else r.raw
        store_idx[(r.store, r.cat)] = (r.dis * raw + N0 * t) / (r.dis + N0)
    def idx(s, c):
        if (s, c) in store_idx: return store_idx[(s, c)]
        t = tier_idx.get((tier[s], c)); return 1.0 if t is None or pd.isna(t) else t
    def base_vel(s, k):
        est = chain_rate.get(k, 0.0) * idx(s, cat_of[k])
        return (sold.get((s, k), 0) + p["PRIOR_DAYS"] * est) / (dis.get((s, k), 0) + p["PRIOR_DAYS"])

    # --- forward demand factor per state and category from wedding dates and festivals
    cal["d"] = pd.to_datetime(cal.date, errors="coerce"); cal = cal.dropna(subset=["d"])
    cal["wed"] = (cal.is_wedding_date == "1").astype(int)
    factor = {}; raw_factor = {}
    try:
        fests = [f for f, n in cal[cal.festival != ""].festival.value_counts().items() if n >= 2]
        states = sorted(set(state.values()))
        feats = {}
        for st_ in states:
            c = cal[cal.state == st_].set_index("d").sort_index()
            days = pd.date_range(min(sales.d.min(), c.index.min()), today + pd.Timedelta(days=p["FORWARD_DAYS"]))
            wed = c.wed.reindex(days).fillna(0).values
            f = pd.DataFrame(index=days)
            f["wed"] = wed
            f["wed_next14"] = pd.Series(wed[::-1]).rolling(14, min_periods=1).sum().values[::-1] / 14.0
            for name in fests:
                fd = c.index[c.festival == name]
                arr = np.zeros(len(days))
                for x in fd:
                    arr[(days >= x - pd.Timedelta(days=14)) & (days <= x)] = 1
                f["f_" + name] = arr
            for wd in range(1, 7): f[f"wd{wd}"] = (days.dayofweek == wd).astype(float)
            feats[st_] = f
        sales_sc = sales.assign(state=sales.store_id.map(state), cat=sales.sku_id.map(cat_of))
        # only stores open through the whole history, so a new store does not look like growth
        old = [s for s in store_ids if pd.isna(opened[s]) or opened[s] <= sales.d.min()]
        sales_sc = sales_sc[sales_sc.store_id.isin(old)] if old else sales_sc
        daily = sales_sc.groupby(["cat", "state", "d"]).qty.sum()
        look = pd.date_range(win_start, win_end); fwd = pd.date_range(today + pd.Timedelta(days=1), today + pd.Timedelta(days=p["FORWARD_DAYS"]))
        for c_ in sorted(prod.category.unique()):
            Xs, ys, keys = [], [], []
            for st_ in states:
                f = feats[st_]; hist = f[(f.index >= sales.d.min()) & (f.index <= today)]
                try: y = daily.loc[(c_, st_)].reindex(hist.index).fillna(0).values
                except KeyError: y = np.zeros(len(hist))
                X = hist.copy()
                for s2 in states[1:]: X["st_" + s2] = float(s2 == st_)
                Xs.append(X); ys.append(y)
            X = pd.concat(Xs); X.insert(0, "const", 1.0); y = np.concatenate(ys)
            if y.sum() < 50:
                for st_ in states: factor[(st_, c_)] = 1.0
                continue
            b = poisson_fit(X.values.astype(float), y.astype(float))
            cols = list(X.columns)
            for st_ in states:
                f = feats[st_].copy()
                for s2 in states[1:]: f["st_" + s2] = float(s2 == st_)
                f.insert(0, "const", 1.0)
                mu = np.exp(np.clip(f[cols].values.astype(float) @ b, -20, 20)); mu = pd.Series(mu, index=f.index)
                ratio = mu.reindex(fwd).mean() / max(mu.reindex(look).mean(), 1e-9)
                factor[(st_, c_)] = float(np.clip(ratio, *p["FACTOR_CLIP"])); raw_factor[(st_, c_)] = float(ratio)
    except Exception as e:  # never let the forecast stop the list
        issue("forecast", "seasonality", f"could not fit the wedding/festival model ({e}); used recent sales speed unchanged")
        factor = {}
    def fac(s, k): return factor.get((state[s], cat_of[k]), 1.0)
    def recv_vel(s, k): return base_vel(s, k) * fac(s, k)                 # what a receiving store is expected to sell per day
    def donor_vel(s, k): return base_vel(s, k) * max(1.0, fac(s, k))      # donors keep stock for the higher of recent and coming demand

    # --- working state
    all_skus = list(I.index)
    out_q = defaultdict(int); in_q = defaultdict(int)          # planned moves per (loc, sku)
    tot_now = {s: sum(on_hand[(s, k)] + in_transit[(s, k)] for k in all_skus) for s in store_ids}
    for s in store_ids:
        if tot_now[s] > cap[s]:
            held = sum(on_hand[(s, k)] for k in all_skus if (s, k) in frozen)
            issue("over capacity", s, f"holds {tot_now[s]} units against a capacity of {cap[s]}" + (f"; {held} of them are disputed stock, so nothing is sent here until it is counted" if held else ""))
    tot_out = defaultdict(int); tot_in = defaultdict(int)
    def projected_total(s): return tot_now[s] + tot_in[s] - tot_out[s]
    def avail(s, k): return on_hand[(s, k)] + in_transit[(s, k)] + in_q[(s, k)] - out_q[(s, k)]
    def givable(s, k): return on_hand[(s, k)] - out_q[(s, k)]   # only stock physically there can leave
    def group_on_hand(s, g): return sum(on_hand[(s, k)] - out_q[(s, k)] for k in all_skus if grp.get(cat_of[k]) == g)
    def style_stock(s, sid): return sum(avail(s, k) for k in skus_of_style[sid])
    st_week = weekly.groupby(["store_id", "style_id", "week_ending"]).dis.max().groupby(level=[0, 1]).sum().to_dict()   # days a style had any size in stock
    def raw_style_vel(s, sid):
        d = st_week.get((s, sid), 0)
        return sum(sold.get((s, k), 0) for k in skus_of_style[sid]) / d if d > 0 else 0.0
    def style_dvel(s, sid): return max(sum(donor_vel(s, k) for k in skus_of_style[sid]), raw_style_vel(s, sid))
    wh_free = {k: on_hand[(WH, k)] for k in all_skus}
    inbound["q"] = to_int(inbound.qty).fillna(0); inbound["d"] = pd.to_datetime(inbound.expected_date, errors="coerce")
    inbound = inbound[inbound.sku_id.isin(I.index) & inbound.d.notna()]
    soon = inbound[inbound.d <= today + pd.Timedelta(days=p["INBOUND_WAIT_DAYS"])]
    inb_free = soon.groupby("sku_id").q.sum().astype(int).to_dict(); inb_date = soon.groupby("sku_id").d.min().to_dict()

    raw_moves = []; blocked = defaultdict(dict)   # rule -> {text: units}; the same refusal is counted once
    def block(rule, text, units):
        blocked[rule][text] = max(blocked[rule].get(text, 0), int(units))

    def max_give(s, k, to):
        """Units of k the store s may give away without breaking a rule. Returns (units, reason_if_zero)."""
        if (s, k) in frozen: return 0, "data issue on this stock"
        sid = style_of[k]; g = givable(s, k)
        if g <= 0: return 0, None
        if tier[s] == "S++" and (s, sid) in protected:
            block("Flagship protection", f"{s} keeps {sid} ({style_name[sid]}): top-20 style at an S++ store", g); return 0, "protected"
        if to != WH:   # donor cover rule applies to store-to-store moves; we also keep it for the size
            dv = style_dvel(s, sid)
            keep_style = math.ceil(dv * p["DONOR_MIN_COVER"] - 1e-9)
            room_style = style_stock(s, sid) - keep_style
            keep_size = math.ceil(donor_vel(s, k) * p["DONOR_MIN_COVER"] - 1e-9)
            room_size = avail(s, k) - keep_size
            room = min(room_style, room_size)
            if room <= 0:
                if excess_units(s, k) > 0: block("Donor cover", f"{s} keeps {k}: giving more would leave under {p['DONOR_MIN_COVER']} days of cover", g)
                return 0, "cover"
            g = min(g, room)
        gname = grp.get(cat_of[k])
        if gname:
            room = group_on_hand(s, gname) - min_for(s, cat_of[k])
            if room <= 0:
                block("Minimum display", f"{s} keeps {k}: {gname} is at its minimum display of {min_for(s, cat_of[k])}", g); return 0, "display"
            g = min(g, room)
        return max(int(g), 0), None

    def room_at(s): return cap[s] - projected_total(s)
    cap_short = defaultdict(int)

    def add(kind, src, dst, k, q, why, dispatch=None, score=0.0):
        q = int(q)
        if q <= 0: return 0
        if dst != WH:
            r = room_at(dst)
            if r <= 0: cap_short[dst] += q; return 0
            if q > r: cap_short[dst] += q - r; q = r
        if src == WH:
            if dispatch is None: wh_free[k] -= q
            else: inb_free[k] -= q
        else:
            out_q[(src, k)] += q; tot_out[src] += q
        if dst != WH:
            in_q[(dst, k)] += q; tot_in[dst] += q
        raw_moves.append(dict(kind=kind, src=src, dst=dst, sku=k, qty=q, why=why, dispatch=dispatch, score=score))
        return q

    def cover_days(units, v): return 999.0 if v <= 1e-9 else units / v

    # --- pass 0: stores over capacity and ageing/excess stock -> to where it sells
    def push_out(s, k, limit, kind, tag):
        """Move up to `limit` units of k out of s to stores that will sell it. Returns units moved."""
        moved = 0
        cands = []
        for t in store_ids:
            if t == s or (t, k) in frozen: continue
            v = recv_vel(t, k)
            if not base_ok(t, k): continue
            L = lead(s, t)
            want = int(math.floor(v * (L + p["PUSH_FILL_COVER"]) + 0.5)) - avail(t, k)
            if want > 0: cands.append((cover_days(avail(t, k), v), L, -v, t, want))
        for cv, L, nv, t, want in sorted(cands):
            if moved >= limit: break
            g, _ = max_give(s, k, t)
            q = min(limit - moved, want, g)
            if q <= 0: continue
            v = -nv
            done = add(kind, s, t, k, q, dict(tag=tag),
                       score=min(q, v * (L + p["PUSH_FILL_COVER"])) * mrp[k])
            moved += done
        return moved

    def excess_units(s, k):
        v = donor_vel(s, k)
        return max(0, givable(s, k) - int(math.ceil(v * p["EXCESS_COVER"])))

    def base_ok(t, k): return base_vel(t, k) >= 0.02      # the receiver must really sell it (about one every seven weeks)

    def pull_back_over(s):
        """A store over capacity sends its excess back until it fits."""
        ks = sorted([k for k in all_skus if givable(s, k) > 0], key=lambda k: (-cover_days(avail(s, k), donor_vel(s, k)), -age.get((s, k), 0)))
        for k in ks:
            overby = projected_total(s) - cap[s]
            if overby <= 0: break
            g, _ = max_give(s, k, WH)
            big = excess_units(s, k)
            ex = min(g, big) if big >= 10 else min(g, big, overby)   # a big stuck lot goes back whole, small lots only as far as needed
            if ex > 0: add("PULL_BACK", s, WH, k, ex, dict(tag="over capacity"), score=0.1 * ex * mrp[k])

    # --- pass 0: excess stock moves to where it sells. Over-capacity stores first, then the oldest stock.
    held_units = {s: sum(on_hand[(s, k)] for k in all_skus if (s, k) in frozen) for s in store_ids}
    over = [s for s in store_ids if tot_now[s] - held_units[s] > cap[s]]   # over capacity on stock we trust; disputed stock is not a reason to strip a store
    lots = []
    for s in store_ids:
        for k in all_skus:
            ex = excess_units(s, k)
            if ex >= p["MIN_PUSH_UNITS"] or (ex > 0 and s in over): lots.append((0 if s in over else 1, -age.get((s, k), 0), s, k))
    for _, na, s, k in sorted(lots):
        ex = excess_units(s, k)
        if ex <= 0: continue
        aged = -na >= p["AGE_DAYS"]
        push_out(s, k, ex, "AGEING" if aged else "STORE_TO_STORE", "over capacity" if s in over else ("ageing" if aged else "excess"))

    # --- pass 1: minimum display. A store below its minimum for a category is topped up before anything else.
    for s in store_ids:
        for g in md_cats:
            m = min_disp.get((tier[s], g), 0)
            have = sum(avail(s, k) for k in all_skus if grp.get(cat_of[k]) == g)
            short = m - have
            if short <= 0: continue
            ks = [k for k in all_skus if grp.get(cat_of[k]) == g and (s, k) not in frozen]
            for rnd in range(4):       # one piece per style-size per round, so the display gets breadth
                cands = []
                for k in ks:
                    if wh_free.get(k, 0) > 0: cands.append((lead(WH, s), -recv_vel(s, k), k, WH))
                    for d_ in store_ids:
                        if d_ != s and givable(d_, k) > 0: cands.append((lead(d_, s), -recv_vel(s, k), k, d_))
                used = set()
                for Ld, nv, k, d_ in sorted(cands):
                    if short <= 0: break
                    if k in used: continue
                    if d_ != WH:
                        gq, _ = max_give(d_, k, s)
                        if gq <= 0: continue
                    elif wh_free.get(k, 0) <= 0: continue
                    got = add("MIN_DISPLAY", d_, s, k, 1, dict(tag="display", group=g, minimum=m, have=have), score=mrp[k] * 0.5)
                    if got: used.add(k); short -= got
            if short > 0: block("Minimum display shortfall", f"{s} is still {short} short of its {g} minimum of {m}: no store or warehouse can give without breaking a rule", short)

    # --- pass 2: stores over capacity pull the rest of their excess back
    for s in over: pull_back_over(s)

    # --- pass 3: top up from the warehouse. Short warehouse -> lowest-cover stores first. Full store -> room shared by cover.
    unmet = {}
    def warehouse_round(pool, dispatch_of=None):
        needs = defaultdict(list)
        for s in store_ids:
            if room_at(s) <= 0: continue
            L = lead(WH, s)
            for k in all_skus:
                if (s, k) in frozen or pool.get(k, 0) <= 0: continue
                v = recv_vel(s, k)
                if v <= 0: continue
                a = avail(s, k)
                if cover_days(a, v) >= L + p["TRIGGER_COVER"]: continue
                want = int(math.floor(v * (L + p["TARGET_COVER"]) + 0.5)) - a
                if want > 0: needs[k].append([s, want, v, a, L])
        plan = defaultdict(list)
        for k, lst in needs.items():
            total = sum(x[1] for x in lst); free = pool.get(k, 0)
            alloc = {x[0]: 0 for x in lst}
            if total <= free:
                for x in lst: alloc[x[0]] = x[1]
            else:
                left = free
                while left > 0:
                    best = None
                    for x in lst:
                        if alloc[x[0]] >= x[1]: continue
                        c = (x[3] + alloc[x[0]]) / x[2]
                        if best is None or c < best[0]: best = (c, x)
                    if best is None: break
                    alloc[best[1][0]] += 1; left -= 1
            for s, want, v, a, L in lst:
                if alloc[s] > 0: plan[s].append([k, alloc[s], v, a, L, total > free, free, total])
                if want - alloc[s] > 0: unmet[(s, k)] = [want - alloc[s], v, a, L]
                else: unmet.pop((s, k), None)
        n = 0
        for s, lst in plan.items():
            room = room_at(s); asked = sum(x[1] for x in lst)
            give = {x[0]: x[1] for x in lst}
            if asked > room:
                # each unit is scored by its chance of selling before the next top-up; ties go to the lower cover
                units_ = []
                for x in lst:
                    k, q0, v, a, L = x[0], x[1], x[2], x[3], x[4]
                    horizon = v * (L + p["TARGET_COVER"])
                    for j in range(q0):
                        units_.append((-max(0.0, min(1.0, horizon - (a + j))), (a + j) / v, k))
                units_.sort()
                give = {x[0]: 0 for x in lst}
                for _, _, k in units_[:max(room, 0)]: give[k] += 1
                cap_short[s] += asked - room
            for k, q0, v, a, L, scarce, free, total in lst:
                q = give[k]
                if q <= 0: continue
                wait = None if dispatch_of is None else (dispatch_of[k] - today).days
                n += add("WAREHOUSE_TO_STORE", WH, s, k, q, dict(scarce=scarce, wh_had=free, wh_asked=total, inbound_wait=wait),
                         dispatch=None if dispatch_of is None else dispatch_of[k], score=min(q, v * (L + p["TARGET_COVER"])) * mrp[k])
        return n
    warehouse_round(wh_free); warehouse_round(wh_free)   # second round hands out what full stores could not take
    warehouse_round(inb_free, inb_date)                  # then deliveries landing at the warehouse within a few days

    # --- pass 4: still short -> another store that holds clearly more than it needs
    for (s, k), (want, v, a, L) in sorted(unmet.items(), key=lambda x: -x[1][1] * mrp[x[0][1]]):
        if wh_free.get(k, 0) > 0 or room_at(s) <= 0: continue
        got = 0
        donors = sorted([(lead(d_, s), -cover_days(avail(d_, k), donor_vel(d_, k)), d_) for d_ in store_ids if d_ != s and givable(d_, k) > 0])
        for Ld, nc, d_ in donors:
            if -nc < p["DONOR_MIN_COVER"] * 2: continue
            w2 = int(math.floor(v * (Ld + p["TARGET_COVER"]) + 0.5)) - avail(s, k)
            g, _ = max_give(d_, k, s)
            q = min(g, max(w2, 0))
            if q <= 0: continue
            got += add("STORE_TO_STORE", d_, s, k, q, dict(tag="under-stocked"), score=min(q, v * (Ld + p["TARGET_COVER"])) * mrp[k])
            if got >= want: break

    # --- pass 5: dead stock that no store has sold: pull back
    chain_style_sold = defaultdict(float)
    for (s, k), q in sold.items(): chain_style_sold[style_of[k]] += q
    for s in store_ids:
        for k in all_skus:
            if givable(s, k) <= 0 or chain_style_sold[style_of[k]] > 0 or age.get((s, k), 0) < p["DEAD_AGE_DAYS"]: continue
            g, _ = max_give(s, k, WH)
            if g > 0: add("PULL_BACK", s, WH, k, g, dict(tag="dead stock"), score=0.1 * g * mrp[k])
    for s in store_ids:
        if projected_total(s) > cap[s]:
            if s in over: block("Capacity", f"{s} is still over capacity after every allowed move ({projected_total(s)} of {cap[s]})", projected_total(s) - cap[s])
        elif cap_short[s] > 0:
            block("Capacity", f"{s} is full after these moves ({projected_total(s)} of {cap[s]}): its room went to the units most likely to sell first, about {cap_short[s]} more units were wanted", cap_short[s])

    # --- group into one line per route and style, write the one-line reason
    groups = defaultdict(list)
    for m in raw_moves: groups[(m["kind"], m["src"], m["dst"], style_of[m["sku"]], str(m["dispatch"]))].append(m)
    size_order = {s: i for i, s in enumerate(["S", "M", "L", "XL", "XXL", "XXXL", "FS"] + [str(n) for n in range(1, 20)])}
    def f1(x): return f"{x:.1f}" if x < 10 else f"{x:.0f}"
    moves = []
    for (kind, src, dst, sid, disp), ms in groups.items():
        bysku = defaultdict(int)
        for m in ms: bysku[m["sku"]] += m["qty"]
        units = sum(bysku.values()); value = sum(q * mrp[k] for k, q in bysku.items())
        L = lead(src, dst); d0 = ms[0]["dispatch"] if ms[0]["dispatch"] is not None else today + pd.Timedelta(days=1)
        sizes = ", ".join(f"{size_of[k]}:{q}" for k, q in sorted(bysku.items(), key=lambda x: size_order.get(size_of[x[0]], 99)))
        w = ms[0]["why"]; nm = style_name[sid]
        fx = factor.get((state[dst], style_cat[sid]), 1.0) if dst != WH else 1.0
        wks = win_days // 7
        def sold_txt(loc):
            n = int(sum(sold.get((loc, k), 0) for k in bysku)); d = sum(dis.get((loc, k), 0) for k in bysku); full = win_days * len(bysku)
            share = d / full if full else 0
            return f"sold {n} in {wks} wks" + (f" (in stock {round(100 * share)}% of the time)" if share < 0.75 else "")
        if dst != WH:
            tv = sum(recv_vel(dst, k) for k in bysku); before = sum(on_hand[(dst, k)] + in_transit[(dst, k)] for k in bysku)
            itq = sum(in_transit[(dst, k)] for k in bysku)
            cb = cover_days(before, tv); ca = cover_days(before + units, tv)
            pace = f"season pace {f1(tv * 7)}/wk" if abs(fx - 1) >= 0.1 else f"pace {f1(tv * 7)}/wk"
            dst_txt = f"{dst} {sold_txt(dst)}, {pace}, has {before}" + (f" ({itq} in transit)" if itq else "") + f" = {f1(min(cb, 999))} days"
        if kind == "WAREHOUSE_TO_STORE":
            extra = ""
            if any(m["why"].get("scarce") for m in ms): extra = " Warehouse is short; lowest-cover stores first."
            if ms[0]["dispatch"] is not None: extra += f" Ships when the delivery lands on {pd.Timestamp(d0).date()}."
            reason = f"{dst_txt}. Send {units} to reach {f1(ca)} days.{extra}"
        elif kind == "MIN_DISPLAY":
            reason = f"{dst} has {w['have']} {w['group']} units, minimum display for a {tier[dst]} store is {w['minimum']}. Send {units}."
        elif kind in ("STORE_TO_STORE", "AGEING"):
            fb = sum(on_hand[(src, k)] + in_transit[(src, k)] for k in bysku); fv = sum(donor_vel(src, k) for k in bysku)
            ages = [age.get((src, k)) for k in bysku if age.get((src, k)) is not None]; oldest = max(ages) if ages else None
            src_txt = f"{src} has {fb}, {sold_txt(src)}" + (f", oldest {oldest} days" if oldest and oldest >= p["AGE_DAYS"] else "")
            keep = fb - units; kc = cover_days(keep, fv)
            reason = f"{src_txt}. {dst_txt}. Move {units}; {src} keeps {keep}" + (f" = {f1(kc)} days." if kc < 999 else ".")
        else:
            fb = sum(on_hand[(src, k)] for k in bysku); ages = [age.get((src, k)) for k in bysku if age.get((src, k)) is not None]
            if w["tag"] == "dead stock": reason = f"No store sold {sid} in {wks} wks and this stock is {max(ages) if ages else '?'} days old. Pull back {units} of {fb}."
            else: reason = f"{src} is over capacity ({tot_now[src]} of {cap[src]}). Has {fb}, {sold_txt(src)}; other stores took what they can sell. Pull back {units}."
        moves.append(dict(kind=kind, from_loc=src, to_loc=dst, style_id=sid, style_name=nm, category=style_cat[sid], sizes=sizes, units=int(units), value_mrp=int(value),
                          needs_approval=bool(value > p["APPROVAL_VALUE"]), lead_days=int(L), dispatch_on=str(pd.Timestamp(d0).date()), arrives_on=str((pd.Timestamp(d0) + pd.Timedelta(days=L)).date()),
                          reason=reason, priority_rs=int(round(sum(m["score"] for m in ms))), skus={k: int(q) for k, q in bysku.items()}))
    kind_rank = {"WAREHOUSE_TO_STORE": 0, "STORE_TO_STORE": 0, "MIN_DISPLAY": 0, "AGEING": 0, "PULL_BACK": 1}
    moves.sort(key=lambda m: (kind_rank[m["kind"]], -m["priority_rs"]))
    for i, m in enumerate(moves, 1): m["move_id"] = f"M{i:04d}"

    am_of = S["area_manager_id"].to_dict() if "area_manager_id" in S.columns else {}
    store_view = []
    for s in store_ids:
        store_view.append(dict(store_id=s, city=city[s], tier=tier[s], capacity=int(cap[s]), units_now=int(tot_now[s]), units_in=int(tot_in[s]), units_out=int(tot_out[s]),
                               units_after=int(projected_total(s)), fill_now=round(100 * tot_now[s] / cap[s]), fill_after=round(100 * projected_total(s) / cap[s]),
                               area_manager_id=am_of.get(s, ""),
                               new_store=bool(not pd.isna(opened[s]) and (today - opened[s]).days < win_days)))

    # Area managers (for the per-role view): name + the stores each one owns, derived from the stores, with names from the table if present.
    am_name = {}; am_city = {}
    for r in amgr.itertuples():
        am_name[r.area_manager_id] = r.name; am_city[r.area_manager_id] = getattr(r, "city", "")
    area_managers_out = []
    owned = defaultdict(list)
    for s in store_ids: owned[am_of.get(s, "")].append(s)
    for amid in sorted(k for k in owned if k):
        area_managers_out.append(dict(area_manager_id=amid, name=am_name.get(amid, amid), city=am_city.get(amid, ""), stores=owned[amid]))

    # Warehouse pick list: for the warehouse role, what to pull on each dispatch day, by SKU.
    pick = defaultdict(lambda: defaultdict(int))
    for m in moves:
        if m["from_loc"] == WH:
            for k, q in m["skus"].items(): pick[m["dispatch_on"]][k] += q
    warehouse_pick = [dict(dispatch_on=d, to_stores=sorted({mm["to_loc"] for mm in moves if mm["from_loc"] == WH and mm["dispatch_on"] == d}),
                           units=int(sum(v.values())), lines=[dict(sku_id=k, style_id=style_of[k], style_name=style_name[style_of[k]], size=size_of[k], qty=int(q)) for k, q in sorted(v.items(), key=lambda x: -x[1])])
                      for d, v in sorted(pick.items())]

    # Problems found, in plain words. The brief hides stock problems and checks whether the system found them.
    problems = []
    def prob(sev, head, detail): problems.append(dict(severity=sev, headline=head, detail=detail))
    if corrected:
        prob("data", f"{len(corrected)} stock figure(s) contradict the weekly history", "; ".join(f"{l} {k}" for (l, k) in list(corrected)[:4]) + " — corrected to the weekly close, please recount")
    sv_by = sorted(store_view, key=lambda x: -(x["units_in"] / x["capacity"]))
    for sv in sv_by[:3]:
        if sv["units_in"] / sv["capacity"] >= 0.3:
            prob("stock", f"{sv['store_id']} ({sv['city']}) was badly understocked", f"only {sv['fill_now']}% full; this list refills {sv['units_in']} units, {round(100 * sv['units_in'] / sv['capacity'])}% of its capacity")
    new_styles = {sid for sid, ld in launch.items() if not pd.isna(ld) and (today - ld).days <= 90}
    ns = defaultdict(int)
    for m in moves:
        if m["style_id"] in new_styles and m["kind"] in ("WAREHOUSE_TO_STORE", "STORE_TO_STORE"): ns[m["style_id"]] += m["units"]
    for sid, u in sorted(ns.items(), key=lambda x: -x[1])[:2]:
        prob("stock", f"new style {style_name[sid]} ({sid}) has not reached the stores that sell it", f"launched {(today - launch[sid]).days} days ago; {u} units are being sent out to stores that have run dry")
    deadu = sum(m["units"] for m in moves if m["kind"] == "PULL_BACK" and m["reason"].startswith("No store"))
    if deadu: prob("stock", f"dead stock is sitting in stores", f"{deadu} unit(s) of styles no store has sold in {win_days // 7} weeks, pulled back to the warehouse")
    aged = sum(m["units"] for m in moves if m["kind"] == "AGEING")
    if aged: prob("stock", f"ageing stock is stuck where it does not sell", f"{aged} unit(s) older than {p['AGE_DAYS']} days moved to stores that are selling the style")
    scarce = sorted({m["style_id"]: m for m in moves if m["why"].get("scarce")}.values(), key=lambda m: -m["units"]) if False else []
    wh_short = sorted({m["style_name"] for m in moves if "Warehouse is short" in m["reason"]})
    if wh_short: prob("supply", f"the warehouse cannot cover demand for {len(wh_short)} style(s)", "; ".join(wh_short[:4]) + " — the lowest-cover stores are served first")
    for sv in store_view:
        if sv["new_store"]: issue("new store", sv["store_id"], f"opened {(today - opened[sv['store_id']]).days} days ago; its sales speed leans on similar stores, not its own short history")
    result = dict(today=str(today.date()), warehouse=WH, window=dict(start=str(win_start.date()), end=str(win_end.date()), days=int(win_days)), params=p,
                  demand_factor={f"{a}|{b}": round(v, 2) for (a, b), v in sorted(factor.items())}, demand_factor_raw={f"{a}|{b}": round(v, 2) for (a, b), v in sorted(raw_factor.items())},
                  corrected_stock=[dict(location_id=a_, sku_id=b_, on_hand=v) for (a_, b_), v in corrected.items()], held_stock=[dict(location_id=a_, sku_id=b_) for (a_, b_) in sorted(frozen)],
                  moves=moves, blocked=[dict(rule=r, units=int(sum(v.values())), cases=len(v), examples=[t for t, _ in sorted(v.items(), key=lambda x: -x[1])[:8]]) for r, v in blocked.items()],
                  issues=issues, stores=store_view, area_managers=area_managers_out, warehouse_pick=warehouse_pick, problems=problems,
                  rules=[dict(rule=r.rule, detail=r.detail) for r in rules.itertuples()])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "moves.json"), "w") as f: json.dump(result, f, indent=1, default=str)
    cols = ["move_id", "kind", "from_loc", "to_loc", "style_id", "style_name", "category", "sizes", "units", "value_mrp", "needs_approval", "dispatch_on", "lead_days", "arrives_on", "priority_rs", "reason"]
    pd.DataFrame(moves, columns=cols + ["skus"]).drop(columns=["skus"]).to_csv(os.path.join(out_dir, "moves.csv"), index=False)
    pd.DataFrame(issues).to_csv(os.path.join(out_dir, "data_issues.csv"), index=False)
    vel_rows = []
    for s in store_ids:
        for k in all_skus:
            oh, it = on_hand[(s, k)], in_transit[(s, k)]; sd, dd = sold.get((s, k), 0), dis.get((s, k), 0)
            if oh == 0 and it == 0 and sd == 0 and in_q[(s, k)] == 0: continue
            bv = base_vel(s, k)
            vel_rows.append(dict(store_id=s, sku_id=k, style_id=style_of[k], sold_in_window=int(sd), in_stock_days=int(dd), raw_per_day=round(sd / dd, 4) if dd else "",
                                 used_per_day=round(bv, 4), season_factor=round(fac(s, k), 2), season_per_day=round(bv * fac(s, k), 4), on_hand=oh, in_transit=it,
                                 cover_days_now=round(min(cover_days(oh + it, bv * fac(s, k)), 999), 1), incoming=in_q[(s, k)], outgoing=out_q[(s, k)], age_days=age.get((s, k), ""), held=(s, k) in frozen))
    pd.DataFrame(vel_rows).to_csv(os.path.join(out_dir, "velocity.csv"), index=False)
    return result

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--out", default="out")
    a = ap.parse_args()
    try: r = run(a.data, a.out)
    except DataError as e: sys.exit(f"DATA PROBLEM: {e}")
    by = defaultdict(lambda: [0, 0])
    for m in r["moves"]: by[m["kind"]][0] += 1; by[m["kind"]][1] += m["units"]
    print(f"today {r['today']}: {len(r['moves'])} moves, {sum(m['units'] for m in r['moves'])} units")
    for k, (n, u) in by.items(): print(f"  {k}: {n} lines, {u} units")
    print(f"  data issues flagged: {len(r['issues'])}; blocked by rules: {sum(b['units'] for b in r['blocked'])} units")
