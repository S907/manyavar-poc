# What is left — detailed backlog

No overview here. Each item says what to change, where, and when it is done. Grouped by area.

Updated after the last build pass. The top section is what is **now done**; the rest is what is
genuinely still open.

---

## Done in this pass (was on this list, now built and tested)

- **Role-based views.** The page has a role switch: Merchandiser (whole list) · Warehouse (what to
  send) · Area manager (their stores only, names from the data) · Store manager (one store). All
  are filters on the same `moves` payload. Backend adds `area_managers` and per-store
  `area_manager_id`, and a `warehouse_pick` list by dispatch day. *Verified on screen.*
- **"Problems found" summary** at the top of the page, in plain words, from a backend `problems`
  audit: data conflicts, understocked stores, a new style that has not reached its stores, dead
  stock, ageing stock, and styles the warehouse cannot cover.
- **~390 lines collapsed into store cards.** The move list opens as ~20 collapsed store cards, each
  with its fill bar and an "approve all" button; a card expands to its lines. "Approve in ten
  minutes" is now real.
- **Rule numbers read from the `rules` file** (30 days of cover, ₹1,00,000 approval), with the code
  constant only as a fallback.
- **Excel workbook accepted** as well as the CSV folder (same loader; the `.xlsx` path is coded but
  untested here because the pack we hold is CSV-only).
- **Survives a broken new pack** — `tests/break_data.py`, 8/8 cases pass: missing optional table,
  missing required column (refused clearly), an unknown store id, text in a numeric column, every
  id lower-cased (nothing hard-coded), no deliveries due, a snapshot date that is not a Saturday,
  and a brand-new category with no minimum-display row.
- **Snapshot reconciled from the weekly history**, with a matching independent check. 11 rule
  checks pass.

---

## Still open

### 1. Engine

- `1.1` **Two or more warehouses.** The code assumes one non-store location and flags if there are
  more. Make the warehouse passes loop over every warehouse and pick the nearest by lead time.
  *Done when a pack with two warehouses plans from both.*
- `1.2` **Mid-week snapshot — reconcile, not just flag.** When the snapshot date is not a
  week-ending date there is no weekly row to compare, so reconciliation is skipped (it is flagged,
  "no cross-check"). Match to the nearest earlier week-ending instead. *Done when a mid-week
  snapshot still gets reconciled.*
- `1.3` **Pull-back lead time.** Not in `lead_times`; assumed equal to warehouse→store for the
  zone (a stated limit). If Manyavar gives a return time, read it. *Done when a stated return time
  is used.*
- `1.4` **Confirm the Excel path on a real workbook** once the `.xlsx` is in hand — load it and
  diff the result against the CSV run. *Done when both give an identical list.*

### 2. Frontend

- `2.1` **A dedicated warehouse pick screen.** The backend already emits `warehouse_pick` (by
  dispatch day, by SKU). The warehouse role currently reuses the store-grouped list; give it the
  pick-by-day view instead. *Done when a picker reads "on 1 Nov, pull N of each SKU".*
- `2.2` **Wire "ask the data" to a real language model** (needs an API key). Keep the current
  lookup as the fallback so a wrong number can never be invented. *Done when a free-text question
  is answered from the data by the model.*

### 3. A full role procedure (only if the judges want handoffs, not just views)

- `3.1` Add a `move_status` table ( move_id, role, state, at ) with states
  `approved → picked → dispatched → received`, and four small routes to move a line along.
  *Done when a store manager can mark a move received and the merchandiser sees it.* The views in
  §0 of the contract work without this; it is only for a live workflow.

### 4. Decisions (need a human, not building)

- `4.1` approvals in the browser (today) vs a server route — pick one.
- `4.2` dataset in the public repo — ask a crew member (still open).
- `4.3` which roles the judges want on screen — ask the Manyavar person.
- `4.4` if snapshot and weekly disagree, is "trust the weekly history" the rule they want? — ask;
  if they say trust the snapshot, flip one line.
