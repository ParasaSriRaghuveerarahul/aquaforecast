import asyncio, os
from contextlib import asynccontextmanager
import json, pathlib, datetime as dt
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import engine as E
from .db import conn, LOCK
from .ingest import ingest_forecast, poll_all, rain_signal, signals, weather_cached
from . import govt, alerts, cwc, ml
import hmac, logging
def poll_secs():
    """AQUA_POLL_SECONDS, default 1200 (20 min); an empty, invalid or too-small value falls back safely."""
    try: return max(60, int((os.environ.get("AQUA_POLL_SECONDS") or "").strip() or 1200))
    except ValueError: return 1200
CITIES = json.loads((pathlib.Path(__file__).parents[2] / "data" / "cities.json").read_text())
POLLER = {}          # job name -> dict(runs, last_start, last_end, last_error, running); shown in /api/data-health
JOBS = (("data poll", poll_all, 1), ("alert check", alerts.check_and_send, 1), ("government feed check", govt.check_all, 1), ("CWC bulletin check", cwc.check, 1))
def _stamp(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
async def _job(name, fn):
    """Each source runs in its OWN loop: a slow or hanging government/CWC download can no longer delay the weather sync (they used to run one after another)."""
    log = logging.getLogger("aquaforecast"); st = POLLER.setdefault(name, dict(runs=0, last_start=None, last_end=None, last_error=None, running=False))
    while True:
        st.update(running=True, last_start=_stamp())
        try: await asyncio.wait_for(asyncio.to_thread(fn, CITIES), timeout=1500); st["last_error"] = None
        except asyncio.TimeoutError: st["last_error"] = "timed out after 25 min"; log.error("%s timed out", name)
        except Exception as e: st["last_error"] = str(e)[:160]; log.exception("%s failed", name)
        st.update(running=False, last_end=_stamp(), runs=st["runs"] + 1)
        await asyncio.sleep(poll_secs())
@asynccontextmanager
async def lifespan(app):
    on = os.environ.get("AQUA_POLL", "1") == "1"
    ts = [asyncio.create_task(_job(n, f)) for n, f, _ in JOBS] if on else []
    POLLER["_enabled"] = on
    yield
    for t in ts: t.cancel()
app = FastAPI(title="AQUAFORECAST API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])
def city(cid):
    if cid not in CITIES: raise HTTPException(404, f"unknown city '{cid}'")
    return CITIES[cid]
class Levers(BaseModel):
    rain: float | None = Field(None, ge=-.6, le=.5); dem: float | None = Field(None, ge=-.3, le=.5)
    ind: float | None = Field(None, ge=0, le=100); rec: float | None = Field(None, ge=0, le=30)
    cap: float | None = Field(None, ge=0, le=40); con: float | None = Field(None, ge=0, le=30)
    rel: float | None = Field(None, ge=0, le=10); ext: float | None = Field(None, ge=0, le=1)
class SimReq(BaseModel):
    city: str; scenario: str = "now"; levers: Levers = Levers()
def build(r):
    c = city(r.city)
    if r.scenario not in E.SCEN: raise HTTPException(422, "unknown scenario")
    return c, {**E.params(c, r.scenario), **r.levers.model_dump(exclude_none=True)}
@app.get("/api/cities")
def cities(): return [dict(id=k, **{x: v[x] for x in ("name", "state", "lat", "lon", "pop_m")}) for k, v in CITIES.items()]
@app.get("/api/cities/{cid}/water-status")
def water_status(cid: str, scenario: str = "now"):
    c = city(cid); p = E.params(c, scenario); s = E.simulate(c, p)
    return dict(city=c["name"], reserve_pct=s["reserve_pct"][0], demand_mld=s["demand"][0], supply_mld=s["supply"][0],
                deficit_mld=s["demand"][0] - s["supply"][0], horizon_days=s["day"], stress=E.status(s["day"]), monte_carlo=E.monte_carlo(c, p),
                why=E.attribution(c, p), provenance=dict(c["status"], source=c["src"], horizon="MODELED (water-balance simulation)", rainfall_scenario="SIMULATED"))
@app.get("/api/cities/{cid}/forecast")
def forecast(cid: str, scenario: str = "now"):
    c = city(cid); return dict(days=list(range(E.TM + 1)), **E.simulate(c, E.params(c, scenario)), status="MODELED")
@app.get("/api/cities/{cid}/rainfall")
def rainfall(cid: str):
    c = city(cid); q = "SELECT date,precip_mm,fetched_at,source FROM rainfall_forecasts WHERE city_id=? ORDER BY date"
    if not conn().execute(q, (cid,)).fetchall() and not ingest_forecast(cid, c): return dict(status="SOURCE CONNECTION FAILED", data=[])
    return dict(status="OFFICIAL FEED (Open-Meteo model forecast)", data=[dict(r) for r in conn().execute(q, (cid,)).fetchall()])
@app.post("/api/simulation")
def simulation(r: SimReq):
    c, p = build(r); s = E.simulate(c, p)
    conn().execute("INSERT INTO simulation_runs(ts,city_id,request,result) VALUES(?,?,?,?)", (dt.datetime.utcnow().isoformat(), r.city, r.model_dump_json(), json.dumps({"day": s["day"]}))); conn().commit()
    return dict(horizon_days=s["day"], stress=E.status(s["day"]), reserve_pct=s["reserve_pct"], why=E.attribution(c, p), monte_carlo=E.monte_carlo(c, p), status="SIMULATED")
@app.post("/api/optimization")
def optimization(r: SimReq):
    c, p = build(r); o = E.optimize(c, p); o["delay_days"] = min(o["horizon_after"], E.TM + 1) - min(o["horizon_before"], E.TM + 1)
    o["method"] = "greedy marginal-benefit search over the simulator; minimum cost to reach a 60-day horizon"; return o
@app.get("/api/cities/{cid}/rain-signal")
def rain_sig(cid: str): city(cid); return rain_signal(cid)
THROUGH = {"daily precipitation forecast": "SELECT MAX(date) FROM rainfall_forecasts", "daily precipitation archive": "SELECT MAX(date) FROM rainfall_observations",
           "daily weather forecast": "SELECT MAX(date) FROM weather_daily WHERE kind='forecast'", "daily weather archive": "SELECT MAX(date) FROM weather_daily WHERE kind='history'",
           "river discharge (GloFAS)": "SELECT MAX(date) FROM river_discharge", "NASA POWER rainfall": "SELECT MAX(date) FROM nasa_rain",
           "reservoir levels (upload)": "SELECT MAX(date) FROM reservoir_observations", "government reservoir feed": "SELECT MAX(data_as_of) FROM govt_feed", "CWC weekly reservoir bulletin": "SELECT MAX(date) FROM cwc_reservoirs"}
def _through(ds):
    try: return conn().execute(THROUGH[ds]).fetchone()[0]
    except Exception: return None
@app.get("/api/cities/{cid}/signals")
def sig(cid: str): city(cid); return signals(cid)
@app.get("/api/data-health")
def data_health():
    now = dt.datetime.now(dt.timezone.utc)
    rows = conn().execute("SELECT source,dataset,city_id,ts,ok,records_valid v,records_rejected r,error FROM data_ingestion_logs ORDER BY ts DESC,id DESC LIMIT 2000").fetchall()
    latest = {}
    for r in rows: latest.setdefault((r["dataset"], r["city_id"]), r)
    out = []; fresh = max(1800, 3 * poll_secs())
    for ds, limit, dsrc in (("daily precipitation forecast", fresh, "Open-Meteo"), ("daily precipitation archive", 129600, "Open-Meteo"), ("daily weather forecast", fresh, "Open-Meteo"), ("daily weather archive", 129600, "Open-Meteo"), ("river discharge (GloFAS)", fresh, "Open-Meteo Flood API"), ("NASA POWER rainfall", 129600, "NASA POWER"), ("reservoir levels (upload)", 259200, "Manual CSV upload"), ("government reservoir feed", 5184000, "Government / utility feed"), ("CWC weekly reservoir bulletin", 864000, "Central Water Commission")):
        L = [r for (d, _), r in latest.items() if d == ds]; okc = [r for r in L if r["ok"]]
        if not L and ds in ("reservoir levels (upload)", "government reservoir feed"): continue     # optional manual/department feeds: shown only once they have been used; the CWC bulletin is the live reservoir feed
        succ = conn().execute("SELECT MAX(ts) FROM data_ingestion_logs WHERE dataset=? AND ok=1", (ds,)).fetchone()[0]
        age = (now - dt.datetime.fromisoformat(succ)).total_seconds() if succ else None
        status = "NO SYNC YET" if not L else "FAILED" if not okc else "STALE" if age > limit else "DEGRADED" if len(okc) < len(L) else "CONNECTED"
        out.append(dict(dataset=ds, source=(L[0]["source"] if L else dsrc), cities_total=len(L), cities_ok=len(okc), valid=sum(r["v"] for r in L), rejected=sum(r["r"] for r in L),
                        last_success_age_s=age, data_through=_through(ds), status=status, last_error=next((r["error"] for r in L if not r["ok"]), None)))
    return dict(poll_seconds=poll_secs(), poller=dict(enabled=POLLER.get("_enabled", False), jobs={k: v for k, v in POLLER.items() if not k.startswith("_")}), datasets=out,
        reported=[dict(dataset="Reservoir capacities and levels", source="Utility and state bulletins (BMC, CMWSSB, GVMC, HMWSSB, DJB)", as_of="typed in from public reports; not auto-fetched", status="OFFICIAL (reported)"),
                  dict(dataset="Demand and supply", source="Utility statements, then modelled", as_of="estimates", status="ESTIMATED")],
        unavailable=["CWC portal (rsms.cwc.gov.in): blocks scripted access, so the bulletin PDF is fetched from the link in data/cwc_source.json instead", "CGWB groundwater stations: not wired (zone depths are indicative)", "IMD station rainfall: not wired (Open-Meteo reanalysis used instead)"])
class Upload(BaseModel):
    csv: str = Field(..., max_length=200_000)
@app.post("/api/reservoir-levels")
def upload_levels(u: Upload):
    import csv, io
    ok, errs = 0, []; today = dt.date.today(); ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = list(csv.DictReader(io.StringIO(u.csv)))
    if not rows or not {"city", "reservoir", "date", "storage_pct"} <= set(rows[0]): raise HTTPException(422, "CSV needs header: city,reservoir,date,storage_pct")
    with LOCK:
        db = conn()
        for i, r in enumerate(rows):
            try:
                cid = r["city"].strip().lower(); d = dt.date.fromisoformat(r["date"].strip()); p = float(r["storage_pct"])
                if cid not in CITIES: raise ValueError(f"unknown city '{cid}'")
                if d > today: raise ValueError("future date")
                if not 0 <= p <= 100: raise ValueError("storage_pct outside 0-100")
                db.execute("INSERT OR REPLACE INTO reservoir_observations VALUES(?,?,?,?,?)", (cid, (r["reservoir"] or "ALL").strip(), d.isoformat(), p, ts)); ok += 1
            except Exception as e: errs.append(f"row {i + 2}: {e}")
        db.execute("INSERT INTO data_ingestion_logs(source,dataset,city_id,ts,records_received,records_valid,records_rejected,ok,error) VALUES(?,?,?,?,?,?,?,?,?)",
                   ("Manual CSV upload", "reservoir levels (upload)", "multi", ts, len(rows), ok, len(errs), int(ok > 0), "; ".join(errs[:3]) or None)); db.commit()
    return dict(accepted=ok, rejected=len(errs), errors=errs[:10])
@app.post("/api/sync/now")
def sync_now():
    """Start one weather/river/rain sync immediately (runs in the background; poll /api/data-health to watch it)."""
    st = POLLER.setdefault("data poll", dict(runs=0, last_start=None, last_end=None, last_error=None, running=False))
    if st.get("running"): return dict(started=False, message="a sync is already running")
    def run():
        st.update(running=True, last_start=_stamp())
        try: poll_all(CITIES); st["last_error"] = None
        except Exception as e: st["last_error"] = str(e)[:160]
        st.update(running=False, last_end=_stamp(), runs=st["runs"] + 1)
    import threading; threading.Thread(target=run, daemon=True).start(); return dict(started=True, message="sync started")
@app.get("/api/govt-feed")
def govt_feed(): return dict(note="Departments release fully current readings about once a month; checked every poll cycle, ingested only when changed.", poll_seconds=poll_secs(), feeds=govt.feed_status(CITIES))
@app.get("/api/cwc-feed")
def cwc_feed(): return cwc.status()
@app.get("/api/ml/validation")
def ml_validation(): return ml.read_report()
@app.get("/api/ml/forecast")
def ml_forecast(reservoir: str | None = None):
    r = ml.read_report()
    if r.get("status") != "OK": return dict(status=r.get("status"), message=r.get("message"), forecasts={})
    f = r["latest_forecasts"]
    if reservoir:
        k = reservoir.strip().upper()
        if k not in f: raise HTTPException(404, f"no ML forecast for '{reservoir}'")
        f = {k: f[k]}
    return dict(status="MODELED (learned, backtested)", data_source=r["data_source"], generated_at=r["generated_at"], band="80% (q10-q90, conformally calibrated)", forecasts=f)
@app.post("/api/cwc-feed/check")
def cwc_check(): cwc.check(CITIES, force=True); return cwc.status()
@app.post("/api/govt-feed/check")
def govt_check(): govt.check_all(CITIES); return govt_feed()
@app.get("/api/cities/{cid}/levels/latest")
def latest_level(cid: str):
    city(cid); r = conn().execute("SELECT reservoir,date,storage_pct,uploaded_at FROM reservoir_observations WHERE city_id=? ORDER BY date DESC, (reservoir='ALL') DESC LIMIT 1", (cid,)).fetchone()
    return dict(available=bool(r), **(dict(r) if r else {}))
@app.get("/api/alerts/status")
def alerts_status(): return alerts.status_info(CITIES)
class AlertTest(BaseModel):
    city: str | None = None
@app.post("/api/alerts/test")
def alerts_test(b: AlertTest = AlertTest(), x_admin_token: str | None = Header(None)):
    tok = os.environ.get("ALERT_ADMIN_TOKEN", "")
    if not tok: raise HTTPException(403, "test sending is disabled: set ALERT_ADMIN_TOKEN on the server")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), tok.encode()): raise HTTPException(401, "bad admin token")
    try: return alerts.send_test(CITIES, b.city)
    except PermissionError as e: raise HTTPException(429, str(e))
    except ValueError as e: raise HTTPException(409, str(e))
class AlertDemo(BaseModel):
    res: float = Field(..., ge=0, le=100); dem: float = Field(..., ge=0, le=5000); sup: float = Field(..., ge=0, le=5000)
@app.post("/api/alerts/demo")
def alerts_demo(b: AlertDemo):
    try: return alerts.send_demo(b.res, b.dem, b.sup)
    except PermissionError as e: raise HTTPException(429, str(e))
    except ValueError as e: raise HTTPException(409, str(e))
# --- compatibility endpoints used by frontend/index.html (same-origin when served by this app) ---
import urllib.request
from fastapi.staticfiles import StaticFiles
class SimCompat(BaseModel):
    city: str; params: dict
@app.post("/api/simulate")
def simulate_compat(r: SimCompat):
    c = city(r.city)
    try: o = E.simulate(c, r.params)
    except KeyError as e: raise HTTPException(422, f"missing parameter {e}")
    return dict(day=o["day"], reserve_pct=o["reserve_pct"][:46])
@app.get("/api/weather")
def weather(lat: float, lon: float):
    try: return weather_cached(lat, lon)
    except Exception: raise HTTPException(502, "SOURCE CONNECTION FAILED")
_fe = pathlib.Path(__file__).parents[2] / "frontend"
if _fe.exists(): app.mount("/", StaticFiles(directory=_fe, html=True), name="ui")
