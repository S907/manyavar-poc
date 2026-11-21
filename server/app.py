"""Stock Mover — full-stack server. One process serves the API and the built React dashboard.

Run:  pip install -r server/requirements.txt
      python server/app.py            # -> http://localhost:8000
It runs the engine if needed, holds the move lifecycle + users + audit in server/state.json,
and enforces who may do what. The frontend talks only to /api/*.
"""
import json, os, sys, subprocess, threading, datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web" / "data"
DIST = ROOT / "dashboard" / "dist"
STATE = Path(__file__).resolve().parent / "state.json"
CSV = ROOT / "data" / "csv"
LIFECYCLE = ["proposed", "approved", "picked", "dispatched", "received"]
lock = threading.Lock()

def run_engine():
    subprocess.run([sys.executable, str(ROOT / "run_daily.py"), "--data", str(CSV)], cwd=str(ROOT), check=True)

def ensure_run():
    if not (DATA / "moves.json").exists():
        run_engine()

def load_json(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def seed_users(run):
    u = [
        {"user_id": "ADMIN", "name": "Super Admin", "email": "admin@manyavar", "role": "super_admin", "scope": {"type": "all"}},
        {"user_id": "MERCH", "name": "HO Merchandiser", "email": "merch@manyavar", "role": "merchandiser", "scope": {"type": "all"}},
        {"user_id": "WH", "name": "Warehouse Desk", "email": "wh@manyavar", "role": "warehouse", "scope": {"type": "warehouse"}},
    ]
    for a in run.get("area_managers", []):
        u.append({"user_id": a["area_manager_id"], "name": a["name"], "email": a["area_manager_id"].lower() + "@manyavar",
                  "role": "area_manager", "scope": {"type": "stores", "stores": list(a["stores"])}})
    for s in run.get("stores", [])[:2]:
        u.append({"user_id": "SM-" + s["store_id"], "name": s["store_id"] + " Store Manager", "email": s["store_id"].lower() + "@manyavar",
                  "role": "store_manager", "scope": {"type": "stores", "stores": [s["store_id"]]}})
    return u

ensure_run()
RUN = load_json(DATA / "moves.json")
CHECK = load_json(DATA / "rule_check.json")
MOVES = {m["move_id"]: m for m in RUN["moves"]}

def load_state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception: pass
    return {"status": {}, "audit": [], "users": None}
STATE_DB = load_state()
if not STATE_DB.get("users"):
    STATE_DB["users"] = seed_users(RUN)
def save_state():
    STATE.write_text(json.dumps(STATE_DB, indent=1), encoding="utf-8")
save_state()

def user(uid): return next((u for u in STATE_DB["users"] if u["user_id"] == uid), None)
def scope_set(u):
    if u["scope"]["type"] in ("all", "warehouse"): return None
    return set(u["scope"].get("stores", []))
def state_of(mid): return STATE_DB["status"].get(mid, "proposed")

def allowed(move, cur, u, to):
    role, W, sc = u["role"], RUN["warehouse"], scope_set(u)
    ins = lambda loc: sc is None or loc in sc
    isHO = role in ("merchandiser", "super_admin")
    opts = []
    if cur == "proposed":
        if isHO: opts += ["approved", "rejected"]
        elif role == "area_manager" and (ins(move["to_loc"]) or ins(move["from_loc"])):
            opts += ["approved_pending_ho" if move["needs_approval"] else "approved"]
    if cur == "approved_pending_ho" and isHO: opts += ["approved"]
    if cur == "approved":
        if role == "warehouse" and move["from_loc"] == W: opts += ["picked"]
        if role == "store_manager" and move["from_loc"] != W and ins(move["from_loc"]): opts += ["dispatched"]
    if cur == "picked" and role == "warehouse" and move["from_loc"] == W: opts += ["dispatched"]
    if cur == "dispatched" and role == "store_manager" and ins(move["to_loc"]): opts += ["received"]
    return to in opts

app = FastAPI(title="Stock Mover")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/run")
def api_run():
    moves = [{**m, "status": state_of(m["move_id"])} for m in RUN["moves"]]
    return {**RUN, "moves": moves, "users": STATE_DB["users"], "audit": STATE_DB["audit"][:300]}

@app.get("/api/checks")
def api_checks(): return CHECK

class Action(BaseModel):
    user_id: str; move_id: str; to: str

@app.post("/api/action")
def api_action(a: Action):
    u = user(a.user_id)
    if not u: raise HTTPException(400, "unknown user")
    move = MOVES.get(a.move_id)
    if not move: raise HTTPException(404, "unknown move")
    with lock:
        cur = state_of(a.move_id)
        if not allowed(move, cur, u, a.to):
            raise HTTPException(403, f"{u['role']} cannot take {a.move_id} from {cur} to {a.to}")
        STATE_DB["status"][a.move_id] = a.to
        STATE_DB["audit"].insert(0, {"at": datetime.datetime.now().isoformat(timespec="seconds"), "user": u["name"],
            "role": u["role"], "action": a.to, "move_id": a.move_id,
            "detail": f"{move['from_loc']}→{move['to_loc']} {move['units']}× {move['style_id']}"})
        save_state()
    return {"ok": True, "status": a.to}

class Bulk(BaseModel):
    user_id: str; move_ids: list[str]; to: str
@app.post("/api/action/bulk")
def api_bulk(b: Bulk):
    u = user(b.user_id)
    if not u: raise HTTPException(400, "unknown user")
    done = []
    with lock:
        for mid in b.move_ids:
            move = MOVES.get(mid); 
            if not move: continue
            cur = state_of(mid)
            if allowed(move, cur, u, b.to):
                STATE_DB["status"][mid] = b.to; done.append(mid)
                STATE_DB["audit"].insert(0, {"at": datetime.datetime.now().isoformat(timespec="seconds"), "user": u["name"],
                    "role": u["role"], "action": b.to, "move_id": mid,
                    "detail": f"{move['from_loc']}→{move['to_loc']} {move['units']}× {move['style_id']}"})
        save_state()
    return {"ok": True, "done": done}

@app.post("/api/rerun")
def api_rerun():
    global RUN, CHECK, MOVES
    with lock:
        run_engine()
        RUN = load_json(DATA / "moves.json"); CHECK = load_json(DATA / "rule_check.json")
        MOVES = {m["move_id"]: m for m in RUN["moves"]}
    return {"ok": True, "moves": len(RUN["moves"]), "rules_pass": CHECK["all_passed"]}

@app.get("/api/health")
def health(): return {"ok": True, "moves": len(RUN["moves"]), "rules_pass": CHECK["all_passed"], "data_date": RUN["today"]}

if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="app")

if __name__ == "__main__":
    print("Stock Mover running on http://localhost:8000  (" + ("frontend built" if DIST.exists() else "frontend NOT built - run: cd dashboard && npm run build") + ")")
    uvicorn.run(app, host="0.0.0.0", port=8000)
