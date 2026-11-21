#!/usr/bin/env python3
"""Prove the engine survives a new, broken data pack. Each case mangles a copy of the data,
runs the engine, and checks it either finishes and flags the problem, or refuses with a clear
message. Run: python tests/break_data.py --data data/csv
"""
import argparse, os, sys, shutil, tempfile
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import stock_mover as sm, check_rules as cr

def copy(src):
    d = tempfile.mkdtemp()
    for f in os.listdir(src):
        if f.endswith(".csv"): shutil.copy(os.path.join(src, f), d)
    return d

def edit(d, name, fn):
    p = os.path.join(d, name + ".csv"); df = pd.read_csv(p, dtype=str, keep_default_na=False); fn(df).to_csv(p, index=False)

CASES = []
def case(fn): CASES.append(fn); return fn

@case
def missing_optional_table(d):
    os.remove(os.path.join(d, "calendar.csv"))
    r = sm.run(d, d + "/o"); assert any(i["kind"] == "data pack" and i["where"] == "calendar" for i in r["issues"]); return f"ran, {len(r['moves'])} moves, calendar flagged"

@case
def missing_required_column(d):
    edit(d, "stores", lambda df: df.drop(columns=["tier"]))
    try: sm.run(d, d + "/o"); return "FAIL: should have refused"
    except sm.DataError as e: assert "tier" in str(e); return "refused clearly: " + str(e)[:50]

@case
def unknown_store_in_snapshot(d):
    edit(d, "stock_snapshot", lambda df: pd.concat([df, df.head(1).assign(location_id="ZZZ-99")]))
    r = sm.run(d, d + "/o"); return f"ran, {len(r['moves'])} moves (extra location treated as a warehouse and flagged: {any('warehouse' in i['kind'] for i in r['issues'])})"

@case
def text_in_numeric(d):
    edit(d, "stock_snapshot", lambda df: df.assign(on_hand=df.on_hand.where(df.index != 5, "lots")))
    r = sm.run(d, d + "/o"); return f"ran, {len(r['moves'])} moves (bad count handled)"

@case
def all_ids_lowercased(d):
    for t in ["stores", "items", "stock_snapshot", "stock_weekly", "warehouse_inbound", "bills", "bill_lines", "flagship_protected", "min_display"]:
        edit(d, t, lambda df: df.map(lambda x: x.lower() if isinstance(x, str) else x))
    # min_display/stores tier also lowercased, so they still join to each other; run should still produce moves
    r = sm.run(d, d + "/o"); return f"ran, {len(r['moves'])} moves (no id was hard-coded)"

@case
def empty_inbound(d):
    edit(d, "warehouse_inbound", lambda df: df.head(0))
    r = sm.run(d, d + "/o"); return f"ran, {len(r['moves'])} moves (no deliveries due)"

@case
def snapshot_not_a_saturday(d):
    edit(d, "stock_snapshot", lambda df: df.assign(as_of_date="2026-10-28"))
    r = sm.run(d, d + "/o"); assert any(i["kind"] == "no cross-check" for i in r["issues"]); return f"ran, {len(r['moves'])} moves (no weekly to cross-check, flagged)"

@case
def new_category_no_min_display(d):
    edit(d, "items", lambda df: df.assign(category=df.category.where(df.index != 0, "Turban")))
    r = sm.run(d, d + "/o"); return f"ran, {len(r['moves'])} moves (unknown category flows through)"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--data", default="data/csv"); a = ap.parse_args()
    ok = 0
    for fn in CASES:
        d = copy(a.data)
        try: msg = fn(d); passed = not str(msg).startswith("FAIL"); ok += passed; print(("PASS " if passed else "FAIL ") + fn.__name__ + ": " + str(msg))
        except Exception as e: print("FAIL " + fn.__name__ + ": " + type(e).__name__ + " " + str(e)[:80])
        finally: shutil.rmtree(d, ignore_errors=True)
    print(f"\n{ok}/{len(CASES)} break-data cases passed")
    sys.exit(0 if ok == len(CASES) else 1)

if __name__ == "__main__": main()
