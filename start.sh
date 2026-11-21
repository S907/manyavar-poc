#!/usr/bin/env bash
# One command to run the whole thing: backend API + built React dashboard on http://localhost:8000
set -e
pip install -r server/requirements.txt
( cd dashboard && npm install && npm run build )
python server/app.py
