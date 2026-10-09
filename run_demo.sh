#!/usr/bin/env bash
# One-command demo.  Usage: NTFY_TOPIC=aquaforecast-yourname-4821 ./run_demo.sh
cd "$(dirname "$0")/backend" && pip install -q -r requirements.txt
export ALERT_PROVIDER="${ALERT_PROVIDER:-ntfy}" NTFY_TOPIC="${NTFY_TOPIC:?set NTFY_TOPIC first}" ALERT_PHONES="${ALERT_PHONES:-9876543210}"
echo "Open http://localhost:8000  ->  Red Alert Demo  ->  Send alert"
python -m uvicorn app.main:app --port 8000
