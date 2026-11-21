#!/usr/bin/env python3
"""One command for the daily run: build the move list, re-check every rule, publish to the web page.
Usage:  python run_daily.py [--data data/csv]
"""
import argparse, json, os, shutil, sys, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import stock_mover, check_rules
ap = argparse.ArgumentParser(); ap.add_argument("--data", default="data/csv"); ap.add_argument("--out", default="out"); a = ap.parse_args()
r = stock_mover.run(a.data, a.out)
c = check_rules.check(a.data, a.out)
meta = dict(generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), data_date=r["today"], moves=len(r["moves"]), units=sum(m["units"] for m in r["moves"]), rules_pass=c["all_passed"])
json.dump(meta, open(os.path.join(a.out, "run.json"), "w"), indent=1)
os.makedirs("web/data", exist_ok=True)
for f in ["moves.json", "rule_check.json", "run.json", "moves.csv", "data_issues.csv", "velocity.csv"]: shutil.copy(os.path.join(a.out, f), os.path.join("web/data", f))
os.makedirs("dashboard/public/data", exist_ok=True)
for f in ["moves.json", "rule_check.json", "run.json"]: shutil.copy(os.path.join(a.out, f), os.path.join("dashboard/public/data", f))
print(json.dumps(meta)); sys.exit(0 if c["all_passed"] else 1)
