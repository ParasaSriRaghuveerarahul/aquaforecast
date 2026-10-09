# Test the red alert in 3 minutes (no SMS account needed)
1. On your phone install the free **ntfy** app (Android / iOS). Tap + and subscribe to a topic, e.g. `aquaforecast-rahul-4821` (make it unique).
2. Windows: edit `NTFY_TOPIC` in `run_demo.bat` to the same name and double-click it.  Mac/Linux: `NTFY_TOPIC=aquaforecast-rahul-4821 ./run_demo.sh`
3. Open http://localhost:8000 > **Red Alert Demo** > press **Critical**, then **Send alert to the control-room phones**.
4. Your phone gets an urgent push with the red alert text within seconds. The result box on the page shows "accepted by ntfy push notification".
For SMS later, use an Indian gateway through `ALERT_PROVIDER=webhook` (see `.env.example`) and `docs/ALERTS_TROUBLESHOOTING.md`.
