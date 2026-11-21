# Run the whole thing

Backend API + the built React dashboard are served by one process on **http://localhost:8000**.

## One command
- Windows: double-click **start.bat** (or run it in a terminal)
- Mac / Linux: `./start.sh`

It installs the Python deps, builds the React app, and starts the server. Open http://localhost:8000.

## Or step by step
```
pip install -r server/requirements.txt       # fastapi, uvicorn, pandas, numpy
cd dashboard && npm install && npm run build  # build the React dashboard -> dashboard/dist
cd .. && python server/app.py                 # serves API + the dashboard at :8000
```

The server runs the stock engine on first start if `web/data/moves.json` is missing, so a fresh
clone with `data/csv/` present just works.

## What connects to what
- **Engine** (`engine/`, `run_daily.py`) turns `data/csv/` into the move list + rule check.
- **Backend** (`server/app.py`, FastAPI) serves `/api/run`, `/api/checks`, `/api/action`,
  `/api/action/bulk`, `/api/rerun`, holds the move lifecycle + users + audit in `server/state.json`,
  and **enforces who may do what** (a warehouse cannot approve; an area manager only their stores).
- **Frontend** (`dashboard/`, React + Vite) talks only to `/api/*`. The server also serves the
  built app, so it is one origin, one URL — no CORS, nothing else to start.

## Reset the demo
Delete `server/state.json` and restart: every move goes back to `proposed`, audit clears.

## Dev mode (optional, hot reload)
Run the API (`python server/app.py`) and in another terminal `cd dashboard && npm run dev`;
Vite proxies `/api` to the server.
