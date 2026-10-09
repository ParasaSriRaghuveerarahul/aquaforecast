# Alert messages are not arriving: checklist

Alerts are sent ONLY at RED (CRITICAL = projected supply-demand failure in under 14 days). Check in this order.

1. **Is any city red?** Open `/api/alerts/status`. Look at `cities[].status`. With the built-in reported levels every city is NORMAL
   except Delhi (WATCH), so NOTHING is sent. That is by design. To prove delivery use the test (step 5). To force a red city for a demo,
   upload a low level: Data panel CSV `city,reservoir,date,storage_pct` / `del,ALL,<today>,8` ; the next poll (up to 10 min) sends once.
2. **Provider.** `provider_label` must not say "dry-run log". Default `ALERT_PROVIDER` is `log` = dry run: the app records "ok" but sends nothing.
   Set `ALERT_PROVIDER=twilio_sms` (or `twilio_whatsapp`, `webhook`) in Render > Environment.
3. **Recipients.** `recipients` must list your numbers. Set `ALERT_PHONES` in Render (comma separated). `invalid_numbers` > 0 means a number was rejected.
4. **Keys.** Twilio needs `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`. `live` must be `true`.
5. **Send a test** (needs `ALERT_ADMIN_TOKEN`; max 5 per hour). PowerShell:
   `Invoke-RestMethod -Method Post -Uri https://YOUR-APP.onrender.com/api/alerts/test -Headers @{"x-admin-token"="YOUR_TOKEN"}`
   The result shows each recipient with ok true/false and the provider's reason. `dry-run` in the detail = nothing was sent.
6. **Provider rules (common real causes).**
   - Twilio trial accounts only message numbers you verified in the Twilio console (error 21608).
   - SMS to Indian numbers needs sender/template registration (DLT); unregistered traffic is often blocked or delayed. Twilio WhatsApp or an Indian
     SMS gateway through `ALERT_PROVIDER=webhook` (MSG91, Fast2SMS, n8n, Make) is usually easier.
   - Twilio WhatsApp sandbox: each phone must first send the "join <code>" message; `TWILIO_FROM` is the sandbox number.
7. **Server asleep.** The free Render server sleeps after about 15 minutes idle and the scheduler stops. Add the UptimeRobot monitor.
8. **Logs.** Render > Logs, and `/api/alerts/status` > `recent` (numbers are masked).
9. **Repeats.** One message when a city enters red, then at most every `ALERT_REPEAT_HOURS` (24). Failed recipients are retried up to 6 times.

## Red Alert Demo page: "Send alert" button
The big red banner on the Red Alert Demo page has **Send alert to the control-room phones**. One click, no token. It sends the message shown on the page
(generic numbers, labelled ILLUSTRATIVE) to the numbers in `ALERT_PHONES` only. Limits: one send per 10 seconds, 5 per hour. If the result box says
"dry-run", set `ALERT_PROVIDER` and the provider keys on the server; until then nothing is delivered.
