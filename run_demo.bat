@echo off
rem One-command demo. Edit the topic name below, then double-click.
set NTFY_TOPIC=aquaforecast-rahul-4821
set ALERT_PROVIDER=ntfy
set ALERT_PHONES=9876543210
cd /d "%~dp0backend"
pip install -q -r requirements.txt
echo Open http://localhost:8000  ^>  Red Alert Demo  ^>  Send alert
python -m uvicorn app.main:app --port 8000
