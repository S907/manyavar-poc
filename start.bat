@echo off
REM One command to run the whole thing on http://localhost:8000
pip install -r server/requirements.txt || exit /b 1
cd dashboard
call npm install
call npm run build
cd ..
python server\app.py
