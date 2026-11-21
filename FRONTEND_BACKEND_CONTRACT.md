# Frontend ⇄ Backend contract

The agreement between the two sides, so each can be built on its own. Hand this to whoever
builds the frontend. Nothing here needs building to read it — it is the spec, not code.

- **Backend** = the planner. It turns the Manyavar data into results.
- **Frontend** = the page. It shows the results and lets a merchandiser approve them.
- **The boundary** = a small set of JSON payloads with a fixed shape. Both sides only have to
  agree on these shapes. The current build ships them as static files in `web/data/`; the same
  shapes can be served from API routes without changing the frontend.

---

## 1. The interface — what backend serves, what frontend reads

Either form works. The frontend reads the **same JSON** whether it comes from a file or a route.

| Purpose | Static file (today) | Equivalent API route (if you add a server) | Shape |
|---|---|---|---|
| The move list + everything about today | `web/data/moves.json` | `GET /api/run/latest` | §3.1 |
| The independent rule check | `web/data/rule_check.json` | `GET /api/run/latest/checks` | §3.2 |
| One-line status | `web/data/run.json` | `GET /api/run/latest/status` | §3.3 |
| Flat move list for download | `web/data/moves.csv` | `GET /api/run/latest/moves.csv` | CSV |
| The number behind each store-size | `web/data/velocity.csv` | `GET /api/run/latest/velocity.csv` | CSV |

**Write actions** (only needed if approvals should be saved on a server instead of in the browser):

| Action | Route | Body |
|---|---|---|
| Save which moves are approved | `POST /api/run/latest/approvals` | `{ "approved_move_ids": ["M0001", "M0007"] }` |
| Read them back | `GET /api/run/latest/approvals` | → the same array |

Until that server exists, the frontend keeps approvals in the browser (localStorage) and exports a
CSV. That is enough for the demo.

---

## 2. Database — tables and how they connect (ready to create)

Two groups of tables: the **input** pack (load once) and the **output** of a run (write each day).
Full column list and types are in `manyavar_schema.pdf`. Keys below are what the backend joins on.

### 2.1 Input tables (the Manyavar pack, 16 tables)

```
area_managers ──< stores ──< bills ──< bill_lines >── items
                    │  │        │                        │  ^
      (state) calendar │        └──> salespeople         │  │ (style_id groups sizes)
                       │                                  │  │
            stock_snapshot >───────── sku_id ────────────┘  │
            stock_weekly   >───────── sku_id ───────────────┤
          warehouse_inbound >──────── sku_id ───────────────┘
            flagship_protected ──(store_id)──> stores,  ──(style_id)──> items
      rules · min_display · lead_times  = settings, joined by tier+category / zone+city
```

Join keys, one per line (left depends on right):

- `stores.area_manager_id` → `area_managers.area_manager_id`
- `stores.state` → `calendar.state` (with a date)
- `stock_snapshot.location_id` → `stores.store_id`, **except `WH-KOL`** which is the warehouse and has no row in `stores`
- `stock_snapshot.sku_id`, `stock_weekly.sku_id`, `warehouse_inbound.sku_id`, `bill_lines.sku_id` → `items.sku_id`
- `stock_weekly.store_id`, `bills.store_id` → `stores.store_id`
- `bill_lines.bill_id` → `bills.bill_id`
- `bills.salesperson_id` → `salespeople.salesperson_id`
- `flagship_protected.store_id` → `stores.store_id`; `flagship_protected.style_id` → `items.style_id`
- `items.style_id` groups all sizes of one design (one style = many sku_id)
- `min_display` joins by `tier` (from stores) + `category` (from items); `lead_times` by `zone` + `city` (from stores)

Rules for the loader (from the pack's readme): IDs are text, keep them text · money is in rupees,
GST included · `is_packaging = 1` rows are not products · the `min_display` "Accessories" row =
Safa + Mala + Stole added together · `area_managers.stores` is a comma-separated list in one cell.

### 2.2 Output tables (what a run produces — persist these if you want a DB instead of files)

- `run` ( run_id PK, data_date, generated_at, moves, units, rules_pass )
- `move` ( move_id, run_id FK, kind, from_loc, to_loc, style_id, style_name, category, sizes,
  units, value_mrp, needs_approval, lead_days, dispatch_on, arrives_on, reason, priority_rs )
- `move_sku` ( move_id FK, sku_id, qty ) — the per-size split
- `store_state` ( run_id FK, store_id, tier, capacity, units_now, units_in, units_out,
  units_after, fill_now, fill_after, new_store )
- `issue` ( run_id FK, kind, where, detail )
- `blocked` ( run_id FK, rule, units, cases, examples )
- `corrected_stock` ( run_id FK, location_id, sku_id, on_hand )
- `rule_result` ( run_id FK, rule, passed, checked, violations, note )
- `approval` ( run_id FK, move_id, approved_bool, approved_by, approved_at )

These mirror the JSON in §3 one-to-one, so moving from files to a database changes nothing for the
frontend.

---

## 3. The exact payload shapes

### 3.1 `moves.json`

Top level: `today`, `warehouse`, `window{start,end,days}`, `params{…}`,
`demand_factor{"state|category": number}`, `demand_factor_raw{…}`, `corrected_stock[]`,
`held_stock[]`, `moves[]`, `blocked[]`, `issues[]`, `stores[]`, `rules[]`.

One **move**: `move_id, kind, from_loc, to_loc, style_id, style_name, category, sizes (string),
skus (object), units, value_mrp, needs_approval (bool), lead_days, dispatch_on, arrives_on,
reason, priority_rs`. `kind` ∈ `WAREHOUSE_TO_STORE, STORE_TO_STORE, MIN_DISPLAY, AGEING, PULL_BACK`.

One **store**: `store_id, city, tier, capacity, units_now, units_in, units_out, units_after,
fill_now, fill_after, new_store`.

One **issue**: `kind, where, detail`. One **blocked**: `rule, units, cases, examples[]`.
One **corrected_stock**: `location_id, sku_id, on_hand`.

### 3.2 `rule_check.json`

`all_passed (bool)`, `moves (int)`, `results[]` where each is
`rule, passed (bool), checked (int), violations (int), examples[], note`.

### 3.3 `run.json`

`generated_at, data_date, moves, units, rules_pass`.

---

## 4. Frontend requirements — what the page must have

Every item names the field that feeds it, so nothing is invented.

**Loading / empty / error:** while fetching show a loading state; if `moves.json` is missing show
"No run yet — ask the backend to run `run_daily.py`". Never show a blank page.

**Header**
- title; `today` (date the list is for); `run.generated_at` (when built)
- a **rule badge**: green "all checks pass" when `rule_check.all_passed` is true, red "N checks
  fail" otherwise

**KPI tiles** (one row): count of `moves`; sum of `units`; sum of `value_mrp`; count where
`needs_approval`; length of `issues`; number of `stores` with `units_in > 0`.

**Move list** (the main view)
- grouped by `to_loc` (pull-backs grouped by `from_loc`)
- each group header: store id, `tier`, `city`, and a fill bar from `fill_now` → `fill_after`
- each row: route `from_loc → to_loc`; a chip for `kind`; `style_name` + `style_id`; `sizes`;
  `units`; `value_mrp`; a "needs approval" mark when `needs_approval`; `arrives_on` + `lead_days`;
  the `reason` text in full
- a checkbox per row to approve; an "approve all" per group
- **filters**: by `kind`, by store, a view switch (all / top-priority / needs-approval), and a text
  search over style, size and reason

**Rule check tab:** the badge, then one line per `results[i]` with a tick/cross, `checked`,
`violations`, `note`, and any `examples`.

**Data issues tab:** one line per `issues[i]` — `kind`, `where`, `detail`. Note on the page that
none of this stock is in any move.

**Blocked tab:** one line per `blocked[i]` — `rule`, `cases`, `units`, `examples`.

**Stores tab:** a table of every `stores[i]` — capacity, now, in, out, after, and a fill bar.

**Ask-the-data:** a text box plus a few canned questions; answers must come only from the loaded
data (no invented numbers). The current page does this as a lookup; a real language model is
optional and needs an API key.

**Sticky footer:** count of approved lines and their total units and value; "approve all routine"
(everything not needing approval); "clear"; "download approved list (CSV)" built from the approved
moves.

The current `web/index.html` already meets all of the above and can be used as the reference, or
rebuilt against this list.

---

## 5. What is left to do (nothing built here — just the list)

**Backend**
- read the rule numbers (30 days, ₹1,00,000, etc.) from the `rules` file instead of code constants
- accept the Excel workbook as well as the CSV folder
- a deliberate break-the-data pass: missing column, two warehouses, a new category with no minimum
  display, a snapshot date that is not a Saturday — prove each fails safely with a clear message
- optional: a tiny server exposing the §1 routes and saving approvals, if approvals should live
  off the browser

**Frontend**
- a "Problems found" summary at the very top, in plain words, before the list
- collapse ~390 lines into ~20 store shipments (a card per store, the lines folded inside)
- optional: wire "ask the data" to a real language model (needs an API key)

**Joint**
- agree whether approvals stay in the browser (today) or move to the server route in §1
