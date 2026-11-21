# Manyavar Stock Mover — Deploy

Full product: FastAPI backend serving the real engine data + the ops board
(stores, live deliveries, forecast, idle, warehouse, exceptions, performance,
insights, automated recommendations with a live Leaflet map).

## Files
- `main.py`            FastAPI app. Serves `/` (board) and `/api/board`, `/api/health`.
- `web/board.html`     The board UI (fetches `/api/board`, falls back to embedded data).
- `web/data/*`         Engine output the API reads (moves.json, velocity.csv).
- `requirements.txt`   fastapi + uvicorn.

## Run locally
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000
    # open http://localhost:8000

## Deploy on Render (2 min)
This branch (`claude-deploy`) is ready. Once it's on GitHub:
1. Render Dashboard -> New -> Web Service -> pick `S907/manyavar-poc`, branch `claude-deploy`.
2. Runtime: Python 3
   Build:  pip install -r requirements.txt
   Start:  uvicorn main:app --host 0.0.0.0 --port $PORT
3. Create. Render gives a public URL. The Leaflet map tiles load on the public internet.

## The one blocker right now
Claude can't push to S907/manyavar-poc (GitHub App has no write for the org).
Fix once: install the Claude GitHub App with write (https://github.com/apps/claude/installations/select_target)
or reconnect GitHub in claude.ai settings. Then Claude pushes `claude-deploy` and Render auto-deploys.

Or push it yourself from this branch:
    git push -u origin claude-deploy
