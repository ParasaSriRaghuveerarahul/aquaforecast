# Alert messages are not arriving: checklist (ntfy)
Alerts go as a phone push through the free ntfy app. Check in this order.
1. **Phone:** ntfy app installed, subscribed to the EXACT same topic as `NTFY_TOPIC` (case-sensitive). Allow notifications for the app; on Android turn off battery optimisation for it.
2. **Server:** `NTFY_TOPIC` is set (Render > Environment, or `run_demo.bat`). `ALERT_PROVIDER=ntfy` (or leave it empty; the topic alone switches ntfy on).
3. **Open `/api/alerts/status`:** `provider` must be `ntfy` and `live` must be `true`. `log` / dry-run means the topic did not reach the server.
4. **Demo page:** Red Alert Demo > CRITICAL > Send alert. The result box must say "accepted by ntfy". A red FAILED line shows the reason (for example a network block to ntfy.sh).
5. **Real red alerts** only send when a city is CRITICAL (failure in under 14 days) and the server is awake. Force one for a demo: Data panel CSV `city,reservoir,date,storage_pct` / `del,ALL,<today>,8`.
6. **Free Render sleeps** after ~15 minutes idle and the checker stops. Add an UptimeRobot monitor.
7. Limits: demo button 1 per 10 s and 5 per hour; repeats of a real red alert at most every `ALERT_REPEAT_HOURS` (24).

## Data sync shows "NO SYNC YET" / stopped
Press **Sync now** in the header, wait 1 to 2 minutes, then open `/api/data-health`. `poller.jobs` shows each background job; each dataset's `last_error` gives the reason.
