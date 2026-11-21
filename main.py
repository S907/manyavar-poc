"""Manyavar Stock Mover — production API + board server.
Serves the real engine output (web/data) as JSON and hosts the ops board."""
import json, csv, collections, pathlib
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

BASE = pathlib.Path(__file__).parent
DATA_DIR = BASE / "web" / "data"

def _f(x):
    try: return float(x)
    except Exception: return 0.0

CITY = {"WH-KOL": (88.36, 22.57), "Lucknow": (80.95, 26.85), "Kanpur": (80.33, 26.45),
        "Patna": (85.14, 25.59), "Muzaffarpur": (85.39, 26.12), "Bengaluru": (77.59, 12.97),
        "Mysuru": (76.65, 12.30)}
REGION = {"Lucknow": "UP North", "Kanpur": "UP North", "Patna": "Bihar East",
          "Muzaffarpur": "Bihar East", "Bengaluru": "Karnataka South", "Mysuru": "Karnataka South"}

def _xy(lon, lat):
    return round((lon-75.5)/(89-75.5)*820+60), round((28-lat)/(28-11.5)*520+50)

def build_board():
    run = json.load(open(DATA_DIR/"moves.json"))
    vel = list(csv.DictReader(open(DATA_DIR/"velocity.csv")))
    by = collections.defaultdict(lambda: dict(sell=0.0, aged=0, oh=0))
    for r in vel:
        s = r["store_id"]; by[s]["sell"] += _f(r["season_per_day"]); by[s]["oh"] += int(_f(r["on_hand"]))
        if r["age_days"] not in ("", "None") and float(r["age_days"]) > 180:
            by[s]["aged"] += int(_f(r["on_hand"]))
    stores = []
    for s in run["stores"]:
        m = by.get(s["store_id"], {}); sell = m.get("sell", 0.0); oh = s["units_now"]
        cover = round(oh/sell, 1) if sell > 0.05 else None; aged = m.get("aged", 0)
        status = ("understocked" if (cover is not None and cover < 12)
                  else "idle-heavy" if (aged > oh*0.25 and oh > 0)
                  else "overstocked" if s["fill_now"] >= 99 else "healthy")
        lon, lat = CITY.get(s["city"], (83, 22)); x, y = _xy(lon, lat)
        stores.append(dict(id=s["store_id"], city=s["city"], zone=s.get("tier", ""), tier=s["tier"],
            cap=s["capacity"], oh=oh, fill=s["fill_now"], fill_after=s["fill_after"], wants=s["units_in"],
            sends=s["units_out"], sell=round(sell, 1), cover=cover, aged=aged, status=status, x=x, y=y,
            lat=lat, lon=lon, am=s.get("area_manager_id", "")))
    whx, why = _xy(*CITY["WH-KOL"]); whlon, whlat = CITY["WH-KOL"]
    ms = [m for m in run["moves"] if m["kind"] in ("WAREHOUSE_TO_STORE", "STORE_TO_STORE")]
    ms.sort(key=lambda m: -m["value_mrp"]); ship = []
    for m in ms[:16]:
        frC = "WH-KOL" if m["from_loc"] == run["warehouse"] else next((s["city"] for s in stores if s["id"] == m["from_loc"]), "")
        toC = next((s["city"] for s in stores if s["id"] == m["to_loc"]), "")
        fl, fla = CITY.get(frC, CITY["WH-KOL"]); tl, tla = CITY.get(toC, (83, 22))
        fx, fy = _xy(*(fl, fla)); tx, ty = _xy(*(tl, tla))
        ship.append(dict(id=m["move_id"], frm=m["from_loc"], to=m["to_loc"], units=m["units"], value=m["value_mrp"],
            kind=m["kind"], style=m["style_name"], style_id=m["style_id"], sizes=m["sizes"], dispatch=m["dispatch_on"],
            arrive=m["arrives_on"], lead=m["lead_days"], reason=m["reason"], fx=fx, fy=fy, tx=tx, ty=ty, status="created"))
    fc = collections.defaultdict(dict)
    for r in vel:
        if r["style_id"] == "KUR-04":
            fc[r["store_id"]][r["sku_id"].split("-")[-1]] = round(_f(r["season_per_day"])*45)
    forecast = dict(style="KUR-04", name="Ivory Chikankari Kurta Set", sizes=["S","M","L","XL","XXL","XXXL"],
        rows=[dict(store=s, cells=[fc.get(s, {}).get(z, 0) for z in ["S","M","L","XL","XXL","XXXL"]])
              for s in sorted(fc) if sum(fc.get(s, {}).values()) > 0][:12])
    idle = []
    for r in vel:
        if r["age_days"] not in ("", "None") and float(r["age_days"]) > 300 and _f(r["sold_in_window"]) == 0 and int(_f(r["on_hand"])) > 0:
            idle.append(dict(store=r["store_id"], sku=r["sku_id"], style=r["style_id"], oh=int(_f(r["on_hand"])), age=int(float(r["age_days"]))))
    idle.sort(key=lambda x: -x["age"])
    ams = [dict(id=a["area_manager_id"], name=a["name"], city=a["city"], stores=a["stores"]) for a in run["area_managers"]]
    lines = []
    for b in run["warehouse_pick"]:
        for ln in b["lines"]:
            lines.append(dict(sku=ln["sku_id"], style=ln["style_id"], name=ln["style_name"], size=ln["size"], qty=ln["qty"]))
    lines.sort(key=lambda x: -x["qty"])
    wh_pick = dict(total=sum(b["units"] for b in run["warehouse_pick"]), lines=lines[:14], nstores=len(run["warehouse_pick"][0]["to_stores"]))
    exc = dict(problems=[dict(sev=p["severity"], head=p["headline"], detail=p["detail"]) for p in run["problems"]],
        issues=[dict(kind=i["kind"], where=i["where"], detail=i["detail"]) for i in run["issues"]],
        blocked=[dict(rule=b["rule"], units=b["units"], cases=b["cases"], ex=b["examples"][:3]) for b in run["blocked"]])
    cityof = {s["id"]: s["city"] for s in stores}; amof = {}
    for a in ams:
        for s in a["stores"]: amof[s] = a["name"]
    seed = [("LKO-01","KUR-04","L",90,"pending"),("PAT-02","SHW-02","M",60,"accepted"),("BLR-03","KUR-09","XXL",40,"pending"),
            ("MYS-01","KUR-02","S",35,"rejected"),("KNP-02","SHW-04","XL",55,"accepted")]
    demands = [dict(id=f"REQ-{i+1:03d}", store=s, city=cityof.get(s, ""), region=REGION.get(cityof.get(s, ""), ""),
        am=amof.get(s, ""), style=st, size=sz, qty=q, status=stt, reason="Store manager flagged low cover")
        for i, (s, st, sz, q, stt) in enumerate(seed)]
    stock = {}
    for r in vel:
        s = r["store_id"]; d45 = round(_f(r["season_per_day"])*45); oh = int(_f(r["on_hand"]))
        if oh == 0 and d45 == 0: continue
        cover = (oh*45/d45) if d45 > 0 else None; need = max(0, d45-oh)
        status = ("dead" if (d45 == 0 and oh > 0) else "short" if (cover is not None and cover < 14)
                  else "over" if (cover is not None and cover > 60) else "ok")
        stock.setdefault(s, []).append(dict(style=r["style_id"], size=r["sku_id"].split("-")[-1], oh=oh, d45=d45, need=need, status=status))
    for s in stock:
        stock[s].sort(key=lambda x: (-x["need"], -x["d45"])); stock[s] = stock[s][:80]
    return dict(today=run["today"], warehouse=dict(id="WH-KOL", city="Kolkata", x=whx, y=why, lat=whlat, lon=whlon),
        stores=stores, shipments=ship, forecast=forecast, idle=idle[:40], problems=run.get("problems", []),
        coords={k: _xy(*v) for k, v in CITY.items()}, ams=ams, wh_pick=wh_pick, exceptions=exc, demands=demands, stock=stock)

BOARD = build_board()
app = FastAPI(title="Manyavar Stock Mover")

@app.get("/api/board")
def api_board():
    return JSONResponse(BOARD)

@app.get("/api/health")
def health():
    return {"ok": True, "stores": len(BOARD["stores"]), "today": BOARD["today"]}

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE/"web"/"board.html").read_text(encoding="utf-8")
