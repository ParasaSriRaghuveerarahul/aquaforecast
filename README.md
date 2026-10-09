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
- Scheduler: backend polls Open-Meteo forecast for every city every 20 minutes (AQUA_POLL_SECONDS, default 1200) and refreshes 5 years of daily rainfall history (ERA5 reanalysis) once a day. AQUA_POLL=0 disables it.
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

Government reservoir feeds (all 8 cities): fully current readings are held by the utilities and water departments, which release them about once a month and do not expose live systems to the public. So `backend/app/govt.py` checks each city's feed on every poll cycle (default 20 minutes) and ingests ONLY when the content changed (SHA-256 of the file/response). Between releases the numbers do not change; a new release is validated, stored with its as-of date and picked up on the next cycle, and the UI applies it automatically within about a minute (toast: "New government data for ...").
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
**Recipients:** `ALERT_PHONES=9876500001,9876500002,9876500003` (10-digit Indian mobiles are normalised to +91). **Provider:** `ALERT_PROVIDER` = `log` (default dry run, nothing leaves the server) | `ntfy` (free phone push; set `NTFY_TOPIC`) | `webhook` (any HTTP service such as MSG91, Fast2SMS or n8n; it receives JSON `{to, message, source}`).
**Go live:** set `NTFY_TOPIC` (with `ALERT_PROVIDER=ntfy`) and subscribe your phone to that topic in the free ntfy app; on Render add them as environment variables (they are declared in `render.yaml` with `sync: false`, so no secret is stored in the repo). Then open *Red Alert Demo* and press **Send a TEST message**; it is clearly labelled as a test and limited to 5 per hour.
**Behaviour:** one message when a city enters red; repeated at most every `ALERT_REPEAT_HOURS` (24) while it stays red; a number that failed is retried on later cycles (max 6) without re-sending to the others; every attempt is logged with numbers masked (`GET /api/alerts/status`).
**Real-world notes:** Indian SMS needs DLT registration with your provider; A free Render instance sleeps without traffic and has a temporary disk, so use an uptime pinger (or a paid instance) if you need alerts to be reliable; after a restart a city that is still red can be alerted once more.
Never commit `.env` (it is git-ignored and docker-ignored).

## v5.2 (Open-Meteo 429 fix)
- Forecast calls to api.open-meteo.com were rejected with HTTP 429 on shared hosts (Render). `_get` now sends a User-Agent, spaces Open-Meteo calls ~0.6 s apart and retries 429/5xx (honouring Retry-After). Each poll cycle makes ONE multi-location request per forecast dataset instead of 16 single-city requests. Per-city error reporting is unchanged: if Open-Meteo still refuses, the Data Health row shows the real error.

## v5.3 (full audit)
- Alerts: `ALERT_PROVIDER` values are trimmed and an empty or mixed-case provider no longer breaks sending (empty = dry-run `log`). Phone numbers with spaces (`+91 98765 00001`) are accepted.
- Poll loop: alerts run first and each step (alerts, government feed, data poll) is isolated, so a crash or slow data poll can never stop alert checks.
- Open-Meteo: after a final HTTP 429 the host is skipped for 5 minutes instead of being hit ~150 times per cycle; `/api/weather` now uses the same User-Agent/throttle and caches each location for 10 minutes.

## v5.4
- Poll interval is now 20 minutes (`AQUA_POLL_SECONDS=1200`, in `render.yaml` and the code default). The STALE threshold for live feeds is now `max(30 min, 3 x poll interval)`, so one missed cycle does not flip a row to STALE.

## v5.5 (interaction layer)
- Home page: a short "idea behind AQUAFORECAST" note (4 rotating principles, written for this project, not attributed to any person) and a live line showing how many data feeds are connected and the countdown to the next sync. Edit the text in `HOME_NOTES` in `frontend/index.html`.
- Data & Sources: "Re-check now" and "Check feeds now" now show a plain-language result (what was checked, what changed, why unchanged values are normal because departments publish about monthly); table rows expand to explain how each source updates; countdown to the next automatic sync.
- Red Alert Demo: a TEST send now shows the per-number result on the page (accepted / failed with the reason), and explains when the TEST button is hidden (ALERT_ADMIN_TOKEN missing).

## v5.6 (CWC bulletin of 8 Oct 2026)
- Loaded the Central Water Commission weekly bulletin (178 reservoirs, 08.10.2026). Typed in by hand from the PDF; not auto-fetched. The six reservoirs used are in `data/cwc_bulletin_2026-10-08.csv`.
- Bengaluru starting level 55% (assumed) -> 40.9% = KRS + Kabini combined live storage (0.658 of 1.607 BCM), used as a proxy for the Cauvery allocation pool. Now tagged REPORTED.
- Shared reservoirs now show CWC levels (display only, not in the model pool): Yeleru 60.6% (Kakinada, Visakhapatnam), Pulichintala 42.5% and Nagarjuna Sagar 30.7% (Vijayawada), Singur 13.5% and Nagarjuna Sagar (Hyderabad).
- Unchanged on purpose: Mumbai (BMC 3 Oct data, different capacity definitions), Chennai (none of its six sources are in the 178), Delhi, and the assumed levels for Kakinada, Vijayawada, Hyderabad and Visakhapatnam.
- Data & Sources: the CWC row moved from NOT CONNECTED to REPORTED (8 Oct 2026).

## v5.7 (CWC weekly bulletin, automatic)
- `backend/app/cwc.py`: every poll cycle (at most every `CWC_CHECK_HOURS`, default 6) downloads the bulletin PDF from `CWC_BULLETIN_URL` (or `data/cwc_source.json`), and only when the file changed parses the 178-reservoir table and stores it. Tested on the 08.10.2026 PDF: 178 rows, totals 184.762 / 130.980 BCM match the bulletin.
- Data & Sources: the CWC row shows LIVE once a download and parse has really succeeded; otherwise OFFLINE, NO SYNC YET, FAILED (with the real error) or STALE (no success for 10 days). It never shows LIVE without a sync.
- New bulletins apply automatically: Bengaluru level (KRS + Kabini) and the shared reservoirs (Yeleru, Pulichintala, Nagarjuna Sagar, Singur) update within about a minute, with a toast.
- API: `GET /api/cwc-feed`, `POST /api/cwc-feed/check`. Also listed in `/api/data-health` as "CWC weekly reservoir bulletin". 35 backend tests pass.
- Source link: the CWC portal (rsms.cwc.gov.in) refused scripted access in testing (HTTP 401), so `data/cwc_source.json` points at a Google Drive copy of the bulletin (must be shared "Anyone with the link"). Replace the file at that link each Thursday, or set `CWC_BULLETIN_URL` to any direct PDF link.
- Not verified: the Drive link downloading from your machine (it asked for sign-in in my test), and any CWC direct link. A Drive link that is not public makes the row show FAILED with "download is not a PDF".

## v5.8 (Reservoir Watch tab)
- New tab "Reservoir Watch": the whole CWC bulletin (178 reservoirs) as a real-data view. Region bars (this year, last year, normal), the upstream CWC sources of each city (Yeleru, Pulichintala, Nagarjuna Sagar, Singur, KRS, Kabini, Bhatsa, Upper Vaitarna) with position against normal, and a filterable reservoir table, lowest against normal first.
- Positions use the bulletin's own definitions (close to normal: shortfall up to 20%; deficient: over 20% and up to 60%; highly deficient: over 60%).
- Works without the backend from a built-in 8 Oct 2026 snapshot; with the backend it shows the latest ingested bulletin (`/api/cwc-feed` now returns the reservoir rows).
- The parsed data reproduces the bulletin's own counts: 26 reservoirs at or below 50% of normal, 71 at or below 80%, totals 184.762 / 130.980 BCM. The bulletin's text says 60 reservoirs are above normal; its own table column gives 63.

## v5.9 (validation rigor)
- Validation tab: new "Baseline check" comparing the model with two naive baselines (level stays flat; straight line from the start) on the real Mumbai 2026 and Chennai 2025-26 reports. Result, stated plainly: a straight line beats the uncalibrated model on both events, so no point-forecast skill over extrapolation is claimed; the model's value is explaining causes and testing scenarios.
- New "Data pipeline check": the automatic CWC parser reproduces the bulletin's reservoir count, total capacity and storage, and the 26 / 71 below-normal counts.
- Not done: calibration on multi-year utility history (needs data that is not public in usable form).

## v5.10 (guided demo)
- Demo is now 14 steps (about 3 minutes at 1x): opens on Reservoir Watch with the CWC numbers (26 of 178 below half of normal, South 47% vs 77%, Singur at 18% of normal), then Chennai in detail, backtests, a new honest baseline step, Data & Sources, and a close that states the limit (demand is estimated) and the next step (a one-city pilot).
- Default voice Microsoft Ravi - English (India) when installed, speed 1x.
- Own voice-over recordings are saved per step number, so recordings made before v5.10 no longer line up. Re-record them from the microphone button.

## v6 (learned early-warning model + rolling backtest)
- `backend/app/ml.py`: forecasts each CWC reservoir's storage 1, 2 and 4 weeks ahead with an 80% band. Quantile gradient boosting (q10/q50/q90) on the weekly change in storage, features = storage, the bulletin's own normal and last-year columns, 1/2/4-week changes, season, capacity, and the normal's seasonal change ahead. The band is widened by split-conformal calibration so it is checked, not assumed, to cover 80%.
- Validation is a rolling-origin backtest (expanding window, last 50% of bulletin dates, 4 folds). A fold trains only on rows whose target was already known at the fold start (unit-tested for no look-ahead). Three baselines are reported: level stays flat, 4-week straight line, flat + the normal's seasonal change. Skill = 1 - model error / baseline error, with a 95% bootstrap interval resampled by bulletin date, against persistence AND against the strongest baseline. Alert metrics (precision, recall, false-alarm rate) are reported for all weeks and for **onset events only** (reservoirs that were at or above 80% of normal and fell below it), with event counts.
- The report states its own limits automatically (for example "not clearly better than the strongest baseline" when the interval includes 0). It refuses to report anything with fewer than 52 bulletin dates (status INSUFFICIENT HISTORY).
- **How to produce the real numbers (needs internet, run on your machine):**
  1. Collect archived CWC weekly bulletin PDFs (one per week, ideally 2+ years) into a folder, or list direct PDF links in `bulletin_urls.txt`.
  2. `cd backend && python scripts/backfill_cwc.py --pdf-dir ../bulletins` (or `--urls bulletin_urls.txt`). It reuses the live parser and validation, and lists every failure.
  3. `python scripts/run_backtest.py` writes `data/ml_report.json` (about 1 minute). The Validation tab and `GET /api/ml/validation`, `GET /api/ml/forecast?reservoir=KABINI` then serve it.
- `python scripts/run_backtest.py --synthetic` rehearses the pipeline on synthetic data and writes a separate file that the API never serves; the UI labels any synthetic report as not real.
- Tests: 44 backend tests pass (9 new for this layer, including no-look-ahead, band coverage, determinism and the insufficient-history guard).
- **Status of results: the pipeline is built and tested on synthetic data only. No accuracy figure for real reservoirs exists until step 3 is run. Do not quote numbers before then.**
- Phone numbers in this README and in the tests are now fake placeholders; real recipients go only in `.env`.

## v6.1 (pre-demo check)
- `python backend/scripts/preflight.py [https://your-app.onrender.com]` reports PASS / WARN / FAIL for: backend reachable, each data feed CONNECTED (with the real error text if not), CWC bulletin feed and its age, alert provider (dry run or real), and whether the served ML report is real. It only reads status endpoints and sends no alerts. Run it ~10 minutes before presenting and again on the venue network. Right after a restart, feeds show NO SYNC YET until the first poll finishes (a minute or two); rerun it.

## v6.2 (interactive Sankey and charts)
- **Water balance Sankey** is now interactive. Hover a source or destination: the flow lights up, the rest dims, and a tooltip shows ML/day, share of total flow, change vs day 0 and its status tag (MODELED / ESTIMATED / SIMULATED / ASSUMPTION / REPORTED). Click (or tap) a flow to pin it and open a detail panel with what drives it: reservoir storage shows how many days the usable storage would last at that draw rate (simple division, consistent with the crisis countdown within a few days); residential shows litres per resident per day; leakage has a "what if leakage fell by X%" slider that shows the water freed and the share of the supply gap it covers (arithmetic on the numbers shown, not a re-run of the simulation).
- **Day slider and Play** on the Sankey drive the global day, so the map, KPIs and charts move together.
- **All line charts** now show a crosshair with a dot per series. On the supply/demand, Monte Carlo and reserve charts, clicking a day jumps the whole dashboard to that day.
- Tested in a headless browser (hover, pin, what-if, slider, play, chart click, city change, mobile tap): no page errors. On phones the Sankey scrolls sideways inside its card (existing responsive rule); tap a flow for its details.


## v6.1 (this package)
- Municipal report rebuilt as a government-style A4 situation report: cover and document control, summary for decision-makers, situation with data-basis tags, outlook chart, zone risk, contributing factors, alerting status, action table with suggested owners, decisions requested (tick boxes), data provenance, confidence and limitations, validation evidence, sign-off block, method and glossary annexes. Page numbers and running footer when printed to PDF. A DRAFT watermark appears when inputs are assumed or the backend is offline. Buttons: Print / Save as PDF, Download HTML.
- Fixed a validation bug present in earlier versions: the Mumbai "uncalibrated error" was computed with whichever city was selected. The true value is 7.8 points.
- Data & Sources page no longer shows a blank screen while the map-tile probe runs.
- Docs: docs/DEPLOY.md (redeploy), docs/ALERTS_TROUBLESHOOTING.md (alert messages not arriving).
- Not verified in the build sandbox: live calls to open-meteo, flood-api.open-meteo, NASA POWER, ntfy, CWC. The ML results table in docs/MODEL_CARD.md is still empty until the CWC archive is backfilled.


## v6.6
- Twilio support removed completely. Alert providers are now ntfy (free phone push), webhook and log. Setting NTFY_TOPIC alone turns ntfy on.

## v6.7
- Reservoir data is now LIVE and weekly: the CWC bulletin (released every Thursday) is checked only from Thursday until the new bulletin appears (every 6 h), then not again until the next Thursday. A failed download is retried hourly.
- Bengaluru's level (KRS + Kabini) from each bulletin is also written to the database, so the Python engine and the red-alert check use the same live number as the screen.
- Removed the permanently empty "reservoir levels (upload)" and "government reservoir feed" rows from Data Health unless they are actually used; department feed cadence is now 7 days. Reservoir Watch shows the next expected bulletin date.
