# AQUAFORECAST (engineering upgrade, phase 1)
Run: `cd backend && pip install fastapi uvicorn pydantic numpy httpx pytest && uvicorn app.main:app --reload` then open http://localhost:8000/docs. Tests: `pytest`.
Full stack: `cp .env.example .env && docker compose up` (PostGIS loads database/schema.sql).
Run everything on one port: uvicorn app.main:app (from backend/) then open http://localhost:8000 . The page serves your original UI; the Backend badge turns green and checks the Python engine against the browser engine.

## What is real
- FastAPI + Pydantic: /api/cities, /water-status, /forecast, /rainfall, POST /api/simulation, POST /api/optimization, /api/data-health.
- Engine (backend/app/engine.py): water balance, 7 scenarios, counterfactual attribution, Monte Carlo, constrained optimizer. Unit-tested.
- Open-Meteo connector (rainfall forecast) with validation and ingestion logging.
- Every metric carries a provenance status (OFFICIAL reported / ESTIMATED / MODELED / SIMULATED).
## Not built yet (honest list)
Next.js + MapLibre frontend wired to the API; PostGIS runtime (API currently uses SQLite for logs; schema.sql is the Postgres target); India-WRIS / CGWB / IMD connectors (no verified open API wired, shown as UNAVAILABLE); historical data and ML forecast comparison (needs real history); auth, reports, alerts, model-health page.
Reference values come from public reports cited per city in data/cities.json; demand and supply are estimates.

## Live data (v2)
- Scheduler: backend polls Open-Meteo forecast for every city every 10 minutes (AQUA_POLL_SECONDS, default 600) and refreshes 5 years of daily rainfall history (ERA5 reanalysis) once a day. AQUA_POLL=0 disables it.
- /api/data-health: per-dataset status (CONNECTED / DEGRADED / STALE / FAILED / NO SYNC YET), valid and rejected record counts, last success age, last error, plus what is reported-only and what is unavailable.
- /api/cities/{id}/rain-signal: observed 30-day rainfall vs the 5-year normal for the same window. LOW confidence flag in dry seasons. The UI can apply it to the simulation (manual button or auto-apply).
- UI: header shows true sync state (LIVE / OFFLINE); Data Health card; click any KPI to trace metric -> calculation -> inputs -> source/status/date.
- Validation tab: leave-one-report-out check added to the Mumbai backtest.
- Not verified in the build sandbox: live calls to open-meteo.com (network blocked there). Ingestion is unit-tested with mocked responses; run it on your machine to confirm.

## v3
- Validation: out-of-sample Chennai backtest (Dec 2025 to Jul 2026, 3 reports, dates approximate). Uncalibrated model overshoots depletion (48.9 pts); Mumbai's fitted term does not transfer (73.6 pts); one Chennai term fits 2.1 pts in-sample, 4.5 pts leave-one-out. Horizons are stress horizons until calibrated per utility.
- Executive tab: "Generate municipal report" builds a printable 9-section report (Print / Save as PDF) from current model state.
- Reservoir CSV upload (POST /api/reservoir-levels, header city,reservoir,date,storage_pct): validated, logged, shown in Data Health (stale after 3 days), applicable to the simulation with its as-of date.
- Tests: 11 backend tests. Live calls to open-meteo.com are not verified in the build sandbox.

## v4 (voice demo and responsive pass)
- Responsive: phone, tablet and desktop layouts; map zoom buttons and touch-friendly charts; smaller label set on phones; wide charts and tables scroll inside their cards; demo bar wraps on small screens.
- Not verified in the build sandbox: how it looks on real devices (no browser available there), and voice quality (tested with a mocked speech engine).


## v4.2 (shorter, faster, natural voice; Data & Sources page)
- Voice choice now ranks natural/neural voices first (for example Microsoft "Natural" voices in Edge), then Google voices, then the rest. Natural tone depends on the voices installed on the device.
- New tab "Data & Sources" (key 6, or open the page with #data): every source, what it is used for, whether it is live, reported, estimated or not connected, and the date its data runs up to. With the backend running it also shows the true sync health (records, last success, last error).
- Mumbai level updated to 95.84% (BMC, 3 Oct 2026).

Government reservoir feeds (all 8 cities): fully current readings are held by the utilities and water departments, which release them about once a month and do not expose live systems to the public. So `backend/app/govt.py` checks each city's feed on every poll cycle (default 10 minutes) and ingests ONLY when the content changed (SHA-256 of the file/response). Between releases the numbers do not change; a new release is validated, stored with its as-of date and picked up on the next cycle, and the UI applies it automatically within about a minute (toast: "New government data for ...").
- Configure per city in `data/govt_sources.json` (authority, `cadence_days`, feed `url` and optional `auth_env`), or drop a CSV at `data/govt_drop/<city>.csv` (header `reservoir,date,storage_pct`; an `ALL` row = total system storage). No department endpoint is wired yet: every city shows NOT CONFIGURED until you provide a file or URL.
- API: `GET /api/govt-feed` (authority, cadence, data as of, next release expected, last checked, last changed, status), `POST /api/govt-feed/check`. Also listed in `/api/data-health`. 15 backend tests pass.
- Public figures can lag the departments' own records; the Data & Sources tab says so next to the per-city table.

Not verified here: real microphone recording, the neural-clip script (needs internet and a service I cannot reach), and how any voice sounds.


## v5
- The second-language narration, its audio files and tooling are removed. The guided demo is English only.
- Data & Sources table: every live-capable source shows LIVE only when it has really synced (from /api/data-health), otherwise OFFLINE, STALE, FAILED, DEGRADED or NO SYNC YET. "Data available up to" comes from the newest record in the database. Ten live-capable rows: backend scheduler, Python engine parity check, Open-Meteo forecast rainfall, forecast temperature + evapotranspiration, historical rainfall, historical temperature + evapotranspiration, Open-Meteo Flood API river discharge, NASA POWER rainfall (independent cross-check), government feed watcher, OpenStreetMap tiles.
- New real keyless sources (all validated and logged; failures are shown, never hidden): Open-Meteo temperature and ET0, Open-Meteo Flood API (GloFAS river discharge), NASA POWER rainfall. Endpoint: GET /api/cities/{id}/signals (temperature, ET0, river discharge vs 30-day mean, 30-day rainfall agreement between two independent sources).
- New page "Red Alert Demo": what a red alert looks like, with GENERIC numbers clearly labelled. No other page uses generic numbers.
- Not verified in the build sandbox: live calls to open-meteo.com, flood-api.open-meteo.com and power.larc.nasa.gov (network blocked there). Ingestion is unit-tested with mocked responses; confirm on your machine that each row turns LIVE.
- Red Alert Demo (v5.1): type your own experimental readings (reserve %, demand, supply) and watch the alert level, countdown, zones and commissioner message react. Includes an alert log, escalation ladder with a demo Acknowledge button, and preset levels. Rule shown on the page: days to failure = (reserve - 15%) x 30,000 ML pool / daily deficit; level thresholds are the same as the live app (60 / 30 / 14 days). All numbers on that page are GENERIC.

## Red-alert SMS / WhatsApp (only the CRITICAL level sends)
Red = projected supply-demand failure in under 14 days (the same rule that colours the Alert Center red). Watch, high-risk and normal never send.
**Recipients:** `ALERT_PHONES=9381244907,6304534629,9440678746` (10-digit Indian mobiles are normalised to +91). **Provider:** `ALERT_PROVIDER` = `log` (default dry run, nothing leaves the server) | `twilio_sms` | `twilio_whatsapp` | `webhook` (any HTTP service such as MSG91, Fast2SMS or n8n; it receives JSON `{to, message, source}`).
**Go live:** set `ALERT_PROVIDER` and the provider keys (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`) plus `ALERT_ADMIN_TOKEN`; on Render add them as environment variables (they are declared in `render.yaml` with `sync: false`, so no secret is stored in the repo). Then open *Red Alert Demo* and press **Send a TEST message**; it is clearly labelled as a test and limited to 5 per hour.
**Behaviour:** one message when a city enters red; repeated at most every `ALERT_REPEAT_HOURS` (24) while it stays red; a number that failed is retried on later cycles (max 6) without re-sending to the others; every attempt is logged with numbers masked (`GET /api/alerts/status`).
**Real-world notes:** Indian SMS needs DLT registration with your provider; a Twilio trial only delivers to verified numbers; WhatsApp sandbox recipients must first send the join code. A free Render instance sleeps without traffic and has a temporary disk, so use an uptime pinger (or a paid instance) if you need alerts to be reliable; after a restart a city that is still red can be alerted once more.
Never commit `.env` (it is git-ignored and docker-ignored).
