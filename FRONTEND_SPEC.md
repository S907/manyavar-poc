# Frontend spec — Stock Mover

Spec-driven. Build each view to this. Every view lists the exact data fields it needs, so the
backend contract and the screen are built from the same source.

The frontend reads one run payload (`GET /api/run/latest`, already filtered to the logged-in user's
scope) plus `GET /api/me`. It never computes stock logic; it renders and sends actions.

---

## 1. Global

- **Login → role.** `GET /api/me` returns `{ user_id, name, role, scope }`. The role decides which
  view loads. No role may see data outside its scope — the backend already filters, the frontend
  must not request wider.
- **Load state.** While fetching show a skeleton; on a missing run show "No run yet"; never a blank
  screen. Show `run.generated_at` and `data_date` on every screen so no one reads a stale list.
- **Rule badge** (all roles): green when `rule_check.all_passed`, red with the fail count otherwise.
- **Status chip** on every move from its lifecycle state: `proposed · approved · picked ·
  dispatched · received · rejected`.

## 2. Shared components (used by several views)

| Component | Reads | Notes |
|---|---|---|
| KPI tile row | counts over `moves`, `issues`, `stores` | lines, units, value, needs-approval, issues |
| Problems panel | `problems[]` → `severity, headline, detail` | top of the list, plain words |
| Store card | a group of `moves` + the matching `stores[]` row | header: store, tier, city, fill bar `fill_now → fill_after`, approve-all; folds to its lines |
| Move row | one `moves[i]` | route, kind chip, style_name+id, sizes, units, value_mrp, needs_approval, arrives_on, reason, status chip, action control |
| Fill bar | `fill_now`, `fill_after` | one bar, before and after |
| Rule check list | `rule_check.results[]` | tick/cross, checked, violations, note, examples |

---

## 3. The views, one by one

Each view: **who**, **purpose**, **data it reads**, **what it can do**, **layout**, **empty/error**.

### 3.1 Super admin

- **Who:** one user who controls all users.
- **Purpose:** manage people and their access, watch the whole operation, fix problems, trigger a
  run, set the data-trust rule.
- **Data it reads:** everything in the run (unfiltered); `GET /api/users`; `GET /api/audit`;
  `GET /api/run/latest/as/:user_id` to see any user's view.
- **What it can do:**
  - **Users tab:** table of `users` (name, email, role, active). Create a user; change role;
    activate / deactivate; assign scope (pick stores, or an area, or warehouse, or all). Fields:
    `user_id, name, email, role, active, scope`.
  - **View-as:** pick a user → load the app read-only exactly as they see it.
  - **Audit tab:** the `audit_log` stream — who approved / picked / dispatched / received / changed
    a user, and when.
  - **Everything the merchandiser can do** (approve, reject, run, export).
  - **Settings:** `snapshot_source` = weekly | snapshot.
- **Layout:** left nav (Overview · Users · Audit · Settings), Overview = the merchandiser screen.
- **Empty/error:** no users yet → "add your first user"; audit empty → "no actions yet".

### 3.2 Merchandiser (head-office planner)

- **Who:** head-office merchandising.
- **Purpose:** approve the whole day's list in ten minutes.
- **Data it reads:** the full run — `moves[], stores[], problems[], issues[], blocked[],
  rule_check`.
- **What it can do:** approve / reject any move (including over ₹1,00,000); approve-all-routine;
  filter (kind, store, top-priority, needs-approval, text); export approved CSV; trigger a run.
- **Layout:** KPI tiles → problems panel → filter bar → **store cards** (collapsed), each
  approvable as a unit; tabs for Rule check, Data issues, Blocked, Stores, Ask-the-data.
- **Empty/error:** no moves → "nothing to move today"; rules failing → red badge, block export.

### 3.3 Area manager

- **Who:** one of six area managers (AM-01…06).
- **Purpose:** approve moves for their own stores only, without the noise of the rest.
- **Data it reads:** the run filtered to their stores (the backend does this from `user_scope`);
  `stores[]` rows for their stores; `area_managers[]` for their name and store list.
- **What it can do:** approve / reject moves within their stores. A `needs_approval` move they
  approve is marked `approved_pending_ho` and must still be signed by HO — show that clearly.
- **Layout:** a one-line summary ("your 4 stores · N moves · M need HO sign-off"), then the store
  cards for their stores only. Respect `max_alerts_per_week`: show the top issues by `value_mrp`
  first.
- **Empty/error:** no moves for their stores → "nothing for your stores today".

### 3.4 Store manager

- **Who:** one store.
- **Purpose:** handle what comes in and what goes out of this store.
- **Data it reads:** the run filtered to their `store_id`.
- **What it can do:** two lists —
  - **Incoming** (`to_loc == my store`): mark **received** once a move is `dispatched`.
  - **Outgoing** (`from_loc == my store`, i.e. store-to-store and pull-backs): mark **dispatched**
    once `approved`/`picked`.
- **Layout:** two stacked lists, Incoming and Outgoing, each a move row with its status chip and the
  one action button for its next state.
- **Empty/error:** nothing in/out → "no transfers for your store today".

### 3.5 Warehouse

- **Who:** the warehouse (WH-KOL).
- **Purpose:** pick and dispatch what head office approved.
- **Data it reads:** `warehouse_pick[]` (by `dispatch_on`, then `lines[]` of `{sku_id, style_id,
  style_name, size, qty}`); and warehouse-origin `moves` for their state.
- **What it can do:** per dispatch day, mark lines **picked** (`approved → picked`) then
  **dispatched** (`picked → dispatched`). Only approved lines appear.
- **Layout:** a tab per `dispatch_on` date; inside, the pick lines grouped by style, with a running
  "picked N of M". A print-friendly pick sheet.
- **Empty/error:** nothing approved yet → "waiting for head office to approve".

---

## 4. Data requirement summary (what the frontend needs, by field)

The frontend needs these and only these from the run; if a field is missing the view degrades
gracefully, it does not crash:

- **identity:** `me.role`, `me.scope`
- **move:** `move_id, kind, from_loc, to_loc, style_id, style_name, category, sizes, skus, units,
  value_mrp, needs_approval, lead_days, dispatch_on, arrives_on, reason, priority_rs, status`
- **store:** `store_id, city, tier, capacity, units_now, units_in, units_out, units_after,
  fill_now, fill_after, area_manager_id, new_store`
- **area_manager:** `area_manager_id, name, city, stores[]`
- **warehouse_pick:** `dispatch_on, to_stores[], units, lines[]{sku_id, style_id, style_name,
  size, qty}`
- **problem:** `severity, headline, detail`
- **issue:** `kind, where, detail` · **blocked:** `rule, units, cases, examples[]`
- **rule check:** `all_passed, results[]{rule, passed, checked, violations, note, examples}`
- **meta:** `today, generated_at, window, warehouse`

## 5. Rules the frontend must respect

- Never request or show data outside the logged-in scope.
- Never show an approve/pick/dispatch/receive button that the role may not use (the backend guards
  it too, but the UI must not offer it).
- "Ask the data" shows only figures present in the payload; if a real language model is wired in,
  it may rephrase but not invent a number.
- Export and "mark dispatched" are disabled while the rule badge is red.

## 6. Build order (frontend)

1. login + `me` + role routing; the shared components in §2
2. merchandiser view (closest to today's page) against the real payload
3. area-manager and store-manager views (scope filter + the two action buttons)
4. warehouse pick screen from `warehouse_pick`
5. super-admin: users, view-as, audit, settings
6. status chips everywhere, driven by the lifecycle state
