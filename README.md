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
