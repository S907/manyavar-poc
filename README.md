# Stock Mover

**Vibe Coders Hackathon Edition 3 · Manyavar (Vedant Fashions) · Case study B**

Every day, find stock that is in the wrong place and produce a **ready-to-approve list**: what to
send from the warehouse, what to move between stores, and what to pull back — each line with a
plain one-line reason, and a second program that re-checks every rule before anything ships.

It is two parts that meet at one folder of JSON:

- **Engine (Python)** — reads the Manyavar data pack, works out demand, writes the move list and
  an independent rule check.
- **Dashboard (React + Vite)** — a merchandising control centre that reads that output: an
  exception-based overview, a transfers workflow, and role views for merchandiser, area manager,
  store manager, warehouse and a super admin.

Modeled on how real allocation/replenishment tools work (Oracle Retail, Anaplan, Increff, Shopify,
Stok.ly): exception-based, days-of-cover, persona dashboards, and a transfer workflow of
approve → pick → dispatch → receive with an audit trail.

---

## Full app (API + dashboard)
See **RUN.md** — one command (`start.bat` / `start.sh`) serves the backend API and the React dashboard at http://localhost:8000.

## Run the engine only

**Windows:** double-click `start.bat`
**Mac/Linux:** `./start.sh`

It installs everything, builds today's list, and opens the dashboard at
**http://localhost:5173**.

Or by hand:

```
pip install -r requirements.txt
python run_daily.py --data data/csv     # builds the list + checks every rule + feeds the dashboard
cd dashboard && npm install && npm run dev
```

In the dashboard, use **“View as”** (top right) to switch roles. Approvals and the audit trail are
live.

---

## What it does, step by step

1. **Velocity** — units sold in the last 12 weeks ÷ the days each size was actually in stock (not
   calendar days), so a size that was out of stock is never read as slow.
2. **Thin history** — a new store, a new style or a mostly-out-of-stock size leans on how the same
   size sells across other stores, scaled by how strong this store is in the category.
3. **Season** — a model on two years of daily sales reads the wedding dates and festivals in the
   calendar and scales demand for the next 45 days (capped at 2.5×, backtested).
4. **Trust the data** — where the snapshot disagrees with the weekly history for the same day, it
   uses the weekly history and records the correction; negative/garbled numbers are flagged and
   held out.
5. **Moves** — excess and ageing stock to stores that sell it; stores below minimum display topped
   up; the warehouse fills the stores that would run short (lowest-cover first when it is short);
   dead stock pulled back.
6. **Rules** — capacity, minimum display, flagship protection, 30 days of donor cover (by style
   and size), in-transit counted once, human approval over ₹1,00,000. All read from the data pack.

## Proven

- **11 independent rule checks pass** — `python engine/check_rules.py --data data/csv --out out`
  (a separate program, re-derived from the raw data, so the planner cannot grade its own work).
- **Survives a broken new pack — 8/8** — `python tests/break_data.py --data data/csv`
  (missing table/column, unknown ids, text in numbers, lower-cased ids, no deliveries, a
  non-Saturday snapshot, a new category).
- **Runs on its own** — `run_daily.py` exits non-zero if any rule fails, so a bad list never ships.
  `.github/workflows/daily.yml` runs it every morning.

## Layout

| Path | What it is |
|---|---|
| `engine/stock_mover.py` | the planner |
| `engine/check_rules.py` | the independent rule check (shares no code with the planner) |
| `run_daily.py` | one command: build → check → feed both frontends |
| `tests/break_data.py` | the break-the-data test pass |
| `dashboard/` | the React dashboard (Vite) |
| `web/` | a single-file HTML version of the same views |
| `data/csv/` | the Manyavar data pack (17 tables) |

## Specs (for anyone extending it)

`BACKEND_SPEC.md`, `FRONTEND_SPEC.md`, `FRONTEND_BACKEND_CONTRACT.md`, `CONTRACT.md` — the data
contract, the database joins, the role views and the super-admin procedure, built for spec-driven
work.

## Notes / limits

- Pull-back lead time is assumed equal to warehouse→store for the zone (not in the pack).
- The dashboard’s roles/approvals are kept in the browser for the demo; the spec has the server
  model for a live deployment.
- Data belongs to Vedant Fashions Limited.
