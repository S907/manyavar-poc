# Backend spec — Stock Mover

Spec-driven. Build to this, not to the current code. The current engine already produces the run
outputs in §5; the new work in this spec is the **users / roles / lifecycle** layer (§3, §4, §6)
that turns a single list into a role-based, super-admin-controlled system.

---

## 1. Purpose

Take the Manyavar data pack and, every day, produce an approvable list of stock moves with a reason
per line and a passing rule check. Then let different roles act on their slice of that list, with
one super-admin controlling every user.

## 2. Inputs

The 17-table data pack (folder of CSVs or the `.xlsx`). Tables, columns and joins are in
`manyavar_schema.pdf` / `FRONTEND_BACKEND_CONTRACT.md §2.1`. The engine reads rule numbers, minimum
displays, lead times and protected styles from their files; it names no store, style or date.

## 3. Data model — run outputs + the new auth layer

### 3.1 Run output tables (already produced as JSON; mirror in DB if persisting)

`run, move, move_sku, store_state, issue, blocked, corrected_stock, rule_result, problem,
area_manager, warehouse_pick` — shapes in `FRONTEND_BACKEND_CONTRACT.md §2.2` and §5 below.

### 3.2 New: users, roles, scope, lifecycle, audit

```
users ( user_id PK, name, email, role, active, created_by, created_at )
      role ∈ super_admin | merchandiser | area_manager | store_manager | warehouse

user_scope ( user_id FK, scope_type, scope_id )
      scope_type ∈ store | area | warehouse | all
      e.g. an area_manager → rows of (store, LKO-01), (store, LKO-02)…  or (area, AM-01)
           a store_manager → one (store, <id>)
           merchandiser / super_admin → (all)

move_status ( run_id FK, move_id FK, state, by_user, at )
      state ∈ proposed | approved | rejected | picked | dispatched | received
      latest row per move_id is the current state

audit_log ( id PK, at, user_id, action, target, detail )
      every write (approve, reject, pick, dispatch, receive, user create/disable, run) is logged
```

The data pack has **no** users; this layer is created by the app. Seed one `super_admin` on first
run. Everything role-based reads `user_scope` to decide what a user may see and do.

## 4. The move lifecycle (state machine)

```
proposed ──approve──> approved ──pick──> picked ──dispatch──> dispatched ──receive──> received
   │                     │
   └──reject──> rejected └──(un-approve)──> proposed
```

- `proposed` is the planner's output. Nothing acts until a move is `approved`.
- Who may trigger each transition is set in §6. Every transition writes `move_status` + `audit_log`.
- A move over ₹1,00,000 (`needs_approval`) cannot leave `proposed` without a merchandiser or
  super-admin; an area manager approving one only marks it `approved_pending_ho`.

## 5. Run output contract (unchanged shapes, for reference)

`moves.json` top level: `today, warehouse, window, params, demand_factor(+_raw), corrected_stock[],
held_stock[], moves[], blocked[], issues[], stores[], rules[], problems[], area_managers[],
warehouse_pick[]`. Field lists are in `FRONTEND_BACKEND_CONTRACT.md §3` and `CONTRACT.md §3`.
`rule_check.json`: `all_passed, moves, results[]`. `run.json`: `generated_at, data_date, moves,
units, rules_pass`.

## 6. API — grouped by who calls it

All reads return the §5 JSON filtered to the caller's `user_scope`. All writes check scope and
write `audit_log`.

### 6.1 Everyone (after login)

- `GET /api/me` → `{ user_id, name, role, scope }`
- `GET /api/run/latest` → the run, **filtered to scope** (a store manager gets only moves touching
  their store; an area manager only their stores; merchandiser/super_admin get everything)
- `GET /api/run/latest/checks` → `rule_check.json` (unfiltered; the rule check is global)
- `GET /api/run/latest/status` → `run.json`

### 6.2 Merchandiser

- `POST /api/moves/approve` `{ move_ids[] }` → set `approved` (any move, including >₹1,00,000)
- `POST /api/moves/reject` `{ move_ids[], reason }`
- `POST /api/run` → re-run the planner on the current data (also allowed to super_admin)
- `GET /api/run/latest/moves.csv` → approved or all, flat

### 6.3 Area manager

- `POST /api/moves/approve` `{ move_ids[] }` → only moves within their stores; a `needs_approval`
  move goes to `approved_pending_ho`, not `approved`

### 6.4 Store manager

- `POST /api/moves/receive` `{ move_ids[] }` → only moves **into** their store, only from
  `dispatched`
- `POST /api/moves/dispatch` `{ move_ids[] }` → only moves **out of** their store (store-to-store,
  pull-back), only from `approved`/`picked`

### 6.5 Warehouse

- `GET /api/run/latest/pick` → `warehouse_pick` (by dispatch day, by SKU)
- `POST /api/moves/pick` `{ move_ids[] }` → `approved` → `picked` (warehouse-origin only)
- `POST /api/moves/dispatch` `{ move_ids[] }` → `picked` → `dispatched`

### 6.6 Super admin (controls all users)

- `GET /api/users` · `POST /api/users` `{ name, email, role }` · `PATCH /api/users/:id`
  `{ role?, active? }` · `POST /api/users/:id/scope` `{ scope_type, scope_ids[] }`
- `GET /api/audit` → the full `audit_log`
- `POST /api/run`, and all merchandiser actions
- `GET /api/run/latest/as/:user_id` → view the run exactly as another user sees it (impersonate for
  support; the view is read-only and itself logged)
- `PATCH /api/settings` `{ snapshot_source }` where `snapshot_source ∈ weekly | snapshot` — which
  source wins when the two disagree (default `weekly`, §8)

## 7. Non-functionals

- **Runs on its own.** `run_daily.py` builds the list, re-checks every rule, and exits non-zero if
  any rule fails, so a bad list never publishes. A schedule runs it daily.
- **Survives a new pack.** `tests/break_data.py` must stay green: missing table/column, unknown
  ids, bad numbers, lower-cased ids, no deliveries, a non-Saturday snapshot, a new category.
- **Deterministic.** The same data gives a byte-identical run.
- **Never invents a number.** "Ask the data" reads from the run; a language model, if added, may
  only quote figures already in the payload.

## 8. Data trust

Where the snapshot and the weekly close for the same day disagree, the engine uses the weekly
history, records the change in `corrected_stock`, and the independent checker re-derives the same
reconciliation. The super-admin can flip the default to trust the snapshot (§6.6).

## 9. Build order (backend)

1. the `users / user_scope / move_status / audit_log` tables + seed a super admin
2. `GET /api/me` and scope-filtering on `GET /api/run/latest`
3. the write routes in §6, each with a scope check and an audit row
4. the lifecycle transitions (§4) with the per-role guards
5. super-admin user management + impersonation + settings
6. keep `tests/break_data.py` and the 11 rule checks green through all of it
