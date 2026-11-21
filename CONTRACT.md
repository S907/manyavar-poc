# Stock Mover — structure for frontend and backend

This is the one file to read before building on top. It shows the whole system in one place
and the exact shape of the data that passes between the backend and the frontend, so each side
can be built without reading the other's code.

Manyavar case study B, Vibe Coders Hackathon Edition 3.

---

## 1. What it is, in one line

The backend reads the Manyavar data pack and writes a **daily list of stock moves** plus a
**rule check**. The frontend reads those files and shows them for approval. Nothing else.

---

## 2. The pipeline

```
  data/csv/ (17 CSV files, the Manyavar data pack)
        │
        ▼
  engine/stock_mover.py        ← the planner: works out velocity, demand, and the moves
        │     writes  →  out/moves.json, moves.csv, velocity.csv, data_issues.csv
        ▼
  engine/check_rules.py        ← independent re-check of every rule (shares no code with the planner)
        │     writes  →  out/rule_check.json
        ▼
  run_daily.py                 ← runs both, then copies everything into web/data/
        │                        exits non-zero if any rule fails, so a bad list never ships
        ▼
  web/data/*.json, *.csv       ← THE CONTRACT. This folder is the only thing the frontend reads.
        │
        ▼
  web/index.html               ← the frontend: move list, rule check, data issues, ask-the-data
```

**The boundary between backend and frontend is the `web/data/` folder.** The backend's job is to
fill it. The frontend's job is to render it. Neither needs to know how the other works. Swap the
frontend, keep the files, and nothing in the backend changes.

---

## 3. The contract — every file the frontend reads

All files live in `web/data/`. The frontend fetches them with plain `fetch()`. No server needed.

### 3.1 `moves.json` — the main file

Top-level keys:

| Key | Type | What it is |
|---|---|---|
| `today` | string `YYYY-MM-DD` | the date the list is for (the snapshot date in the data) |
| `warehouse` | string | the warehouse location id, e.g. `WH-KOL` |
| `window` | object | `{start, end, days}` — the period the sales speed was measured over |
| `params` | object | the settings used (cover targets, thresholds); see §6 |
| `demand_factor` | object | `"<state>|<category>": number` — the seasonal multiplier used |
| `demand_factor_raw` | object | the same before the cap, for transparency |
| `corrected_stock` | array | snapshot values changed to match the weekly history (see §4) |
| `held_stock` | array | stock left out of every move because it could not be trusted |
| `moves` | array | **the move list** — one object per line, shape below |
| `blocked` | array | moves the planner wanted but a rule stopped |
| `issues` | array | data that does not look right, flagged not acted on |
| `stores` | array | every store, before and after this list |
| `rules` | array | the stock rules, as Manyavar wrote them |
| `problems` | array | plain-language problems found, for the top-of-page summary: `{severity, headline, detail}` |
| `area_managers` | array | `{area_manager_id, name, city, stores[]}` — for the area-manager role view |
| `warehouse_pick` | array | by dispatch day: `{dispatch_on, to_stores[], units, lines[]}` — for the warehouse role |

**One move** (`moves[i]`):

| Field | Type | Meaning |
|---|---|---|
| `move_id` | string | `M0001`, stable id for the line |
| `kind` | enum | `WAREHOUSE_TO_STORE` · `STORE_TO_STORE` · `MIN_DISPLAY` · `AGEING` · `PULL_BACK` |
| `from_loc` | string | source store or warehouse id |
| `to_loc` | string | destination store or warehouse id |
| `style_id` | string | the design, e.g. `KUR-04` |
| `style_name` | string | human name of the design |
| `category` | string | Sherwani, Kurta Set, … |
| `sizes` | string | `"S:3, M:30, L:31"` — units per size, display-ready |
| `skus` | object | `{"KUR-04-S": 3, …}` — the same, machine-readable |
| `units` | int | total units on the line |
| `value_mrp` | int | rupees at MRP |
| `needs_approval` | bool | true if over ₹1,00,000 (a human must sign it) |
| `lead_days` | int | days the move takes |
| `dispatch_on` | string date | when it should leave |
| `arrives_on` | string date | when it lands |
| `reason` | string | the one-line explanation, already written |
| `priority_rs` | int | ranking score; the list is sorted by this |

**One store** (`stores[i]`): `store_id, city, tier, capacity, units_now, units_in, units_out,
units_after, fill_now, fill_after, new_store`.

**One issue** (`issues[i]`): `{kind, where, detail}`.

**One blocked group** (`blocked[i]`): `{rule, units, cases, examples[]}`.

**One corrected-stock row** (`corrected_stock[i]`): `{location_id, sku_id, on_hand}` — the value the
planner used after reconciling the snapshot against the weekly history.

### 3.2 `rule_check.json` — the independent check

| Key | Type | Meaning |
|---|---|---|
| `all_passed` | bool | true only if every check passed |
| `moves` | int | how many moves were checked |
| `results` | array | one per rule: `{rule, passed, checked, violations, examples[], note}` |

The frontend shows the badge from `all_passed` and the list from `results`.

### 3.3 `run.json` — one-line status

`{generated_at, data_date, moves, units, rules_pass}` — for a header or a health check.

### 3.4 CSV files (for download or a spreadsheet, not needed by the page)

- `moves.csv` — the move list, flat. Columns: `move_id, kind, from_loc, to_loc, style_id,
  style_name, category, sizes, units, value_mrp, needs_approval, dispatch_on, lead_days,
  arrives_on, priority_rs, reason`.
- `velocity.csv` — the number behind every store-and-size: `store_id, sku_id, style_id,
  sold_in_window, in_stock_days, raw_per_day, used_per_day, season_factor, season_per_day,
  on_hand, in_transit, cover_days_now, incoming, outgoing, age_days, held`. This is the file a
  judge uses to spot-check a number.
- `data_issues.csv` — `kind, where, detail`.

---

## 4. "The snapshot is not a worry" — how stock numbers are settled

The snapshot (one figure per store-and-size on 31 Oct) and the weekly table (the same figure for
each of the last 12 weeks) both ship in the pack, and in two places they disagree. **The engine
settles this from the data, not from any written rule:** the weekly close is one row of a
consistent 12-week series, so where the single snapshot figure disagrees with it, the engine uses
the weekly close, records the change in `corrected_stock`, and carries on. A negative count with no
weekly figure to fall back on is treated as 0 and listed in `issues`. The independent checker
re-does the same reconciliation from the raw files, so it agrees without trusting the engine.

Result: no store is left looking over capacity because of a bad number, and every change is
visible on the page. This is handled; it is not a thing to keep solving.

---

## 5. Input data

The 17 CSV files of the Manyavar data pack, in `data/csv/`. Every table, column and join is in
`manyavar_schema.pdf` (the schema document) and in the pack's own `data_dictionary.csv`. The
engine names no store, style or date: "today" is the snapshot date, and the rules, minimum
displays, lead times and protected styles are read from their files, so a new pack with the same
columns runs as is.

---

## 6. Settings (the `params` block, top of `engine/stock_mover.py`)

All tuning lives in one place. Current values: top-up aims for **21** days of cover after arrival;
top up when cover would fall below **lead time + 10** days; a giving store keeps **30** days of
cover; stock older than **180** days is ageing; cover above **120** days is excess; the seasonal
multiplier is capped at **2.5×**; a move over **₹1,00,000** needs human approval. Changing a number
here changes the whole list. (These are still read from constants, not yet from the rules file —
see §7.)

---

## 7. Baseline vs cherries

**Baseline — built and passing (this is the solid floor to develop on):**

- velocity from units sold ÷ days actually in stock, with a peer estimate for thin history
- a seasonal demand model from the wedding and festival calendar, capped and backtested
- all five move kinds: warehouse→store, store→store, minimum display, ageing, pull-back
- every rule enforced: capacity, minimum display, flagship protection, donor cover (style and
  size), in-transit counted once, approval over ₹1,00,000
- snapshot reconciled from the weekly history (§4)
- an independent rule checker, 11 checks, all passing
- one-command daily run, exits non-zero on any rule break
- a working page: list by store, rule check, data issues, blocked moves, ask-the-data, CSV export

**Cherries — not built, safe to add on top without touching the baseline:**

- a "Problems found" summary at the top, in plain words, before the list
- collapse ~390 lines into ~20 shipments (one card per store, lines inside)
- read the rule numbers (30 days, ₹1,00,000) from the rules file instead of constants
- accept the Excel workbook as well as the CSVs
- a real LLM behind "ask the data" (needs an API key)
- a deliberate break-the-data test pass (missing column, two warehouses, a new category)

---

## 8. Run it

```
pip install -r requirements.txt
python run_daily.py --data data/csv      # fills web/data/
python -m http.server -d web 8000        # open http://localhost:8000
```

`.github/workflows/daily.yml` runs the same command every morning with no one watching.
