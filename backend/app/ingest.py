"""Open-Meteo connectors (public, keyless; https://open-meteo.com/en/docs). Forecast = model forecast; archive = ERA5-based
reanalysis (not rain-gauge data). Every run is validated and logged. No synthetic fallback: failures are recorded, not hidden."""
import json, urllib.request, datetime as dt
from .db import conn, LOCK
FC = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum&forecast_days=7&timezone=auto"
AR = "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={a}&end_date={b}&daily=precipitation_sum&timezone=auto"
import time, threading, urllib.error
_UA = "AquaForecast/5 (hackathon demo; non-commercial; contact via project repo)"
_GAP, _LAST, _GLOCK, _PRE, _COOL = 0.6, [0.0], threading.Lock(), {}, {}
def _get(u, tries=3):
    """GET json. Serves a prefetched per-city response if present; spaces out Open-Meteo calls; retries 429/5xx honouring Retry-After."""
    hit = _PRE.pop(u, None)
    if hit and time.monotonic() - hit[0] < 300: return hit[1]
    host = u.split("/")[2]; cd = _COOL.get(host)
    if cd and time.monotonic() < cd: raise RuntimeError(f"HTTP Error 429: Too Many Requests ({host} is rate-limiting this server; will retry next cycle)")
    for i in range(tries):
        if "open-meteo.com" in u:
            with _GLOCK:
                w = _LAST[0] + _GAP - time.monotonic()
                if w > 0: time.sleep(w)
                _LAST[0] = time.monotonic()
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": _UA}), timeout=20))
        except urllib.error.HTTPError as e:
            if e.code == 429 and i == tries - 1: _COOL[host] = time.monotonic() + 300
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1: raise
            try: ra = float(e.headers.get("Retry-After", ""))
            except (TypeError, ValueError): ra = 0.0
            time.sleep(min(max(ra, 4.0 * 2 ** i), 30.0))
_WX = {}
def weather_cached(lat, lon):
    """Used by /api/weather: same User-Agent/throttle as the poller, one upstream call per location per 10 minutes."""
    k = (round(float(lat), 3), round(float(lon), 3)); h = _WX.get(k)
    if h and time.monotonic() - h[0] < 600: return h[1]
    j = _get(FC.format(lat=k[0], lon=k[1]), tries=1)
    if len(_WX) > 200: _WX.clear()
    _WX[k] = (time.monotonic(), j); return j
def _prefetch(template, cities):
    """ONE multi-location request for all cities (Open-Meteo accepts comma-separated coordinates); each city's slice is cached under its own URL so the per-city ingest code is unchanged. Failure is silent here: the normal per-city call then runs and records the real error."""
    ids = list(cities)
    try:
        j = _get(template.format(lat=",".join(str(cities[i]["lat"]) for i in ids), lon=",".join(str(cities[i]["lon"]) for i in ids)))
        j = [j] if isinstance(j, dict) else j
        if len(j) != len(ids): return
        for i, r in zip(ids, j): _PRE[template.format(**cities[i])] = (time.monotonic(), r)
    except Exception: pass
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def _log(dataset, cid, rec, valid, err, src="open-meteo"):
    with LOCK:
        d = conn(); d.execute("INSERT INTO data_ingestion_logs(source,dataset,city_id,ts,records_received,records_valid,records_rejected,ok,error) VALUES(?,?,?,?,?,?,?,?,?)",
                              (src, dataset, cid, now(), rec, valid, rec - valid, int(err is None), err)); d.commit()
def _store(table, cid, rows):
    valid = 0
    with LOCK:
        d = conn()
        for day, v in rows:
            if v is None or not (0 <= v < 1000): continue
            d.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?)", (cid, day, v, now(), "open-meteo")); valid += 1
        d.commit()
    return valid
def ingest_forecast(cid, c):
    rec = valid = 0; err = None
    try:
        j = _get(FC.format(**c)); rows = list(zip(j["daily"]["time"], j["daily"]["precipitation_sum"])); rec = len(rows); valid = _store("rainfall_forecasts", cid, rows)
    except Exception as e: err = str(e)[:200]
    _log("daily precipitation forecast", cid, rec, valid, err); return err is None
def ingest_history(cid, c, today=None):
    today = today or dt.date.today(); rec = valid = 0; err = None
    try:
        a = today.replace(year=today.year - 5, month=1, day=1); b = today - dt.timedelta(days=5)
        j = _get(AR.format(a=a, b=b, **c)); rows = list(zip(j["daily"]["time"], j["daily"]["precipitation_sum"])); rec = len(rows); valid = _store("rainfall_observations", cid, rows)
    except Exception as e: err = str(e)[:200]
    _log("daily precipitation archive", cid, rec, valid, err); return err is None
def history_due(cid):
    r = conn().execute("SELECT MAX(ts) FROM data_ingestion_logs WHERE dataset='daily precipitation archive' AND city_id=? AND ok=1", (cid,)).fetchone()[0]
    return not r or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(r)).total_seconds() > 86400
def poll_all(cities):
    _prefetch(FC, cities); _prefetch(FCW, cities)
    for cid, c in cities.items():
        ingest_forecast(cid, c); ingest_weather_forecast(cid, c); ingest_flood(cid, c)
        if history_due(cid): ingest_history(cid, c)
        if due("daily weather archive", cid): ingest_weather_history(cid, c)
        if due("NASA POWER rainfall", cid): ingest_nasa(cid, c)
def rain_signal(cid, today=None):
    today = today or dt.date.today(); end = today - dt.timedelta(days=5); start = end - dt.timedelta(days=29); db = conn()
    def tot(a, b):
        r = db.execute("SELECT SUM(precip_mm),COUNT(*) FROM rainfall_observations WHERE city_id=? AND date BETWEEN ? AND ?", (cid, a.isoformat(), b.isoformat())).fetchone(); return r[0], r[1]
    obs, n = tot(start, end)
    if not n or n < 25: return dict(available=False, reason="rainfall history not ingested yet")
    clim = []
    for k in range(1, 6):
        try: s, m = tot(start.replace(year=start.year - k), end.replace(year=end.year - k))
        except ValueError: continue
        if m >= 25: clim.append(s)
    if len(clim) < 3: return dict(available=False, reason="fewer than 3 comparison years")
    normal = sum(clim) / len(clim); f = db.execute("SELECT SUM(precip_mm),MAX(fetched_at) FROM rainfall_forecasts WHERE city_id=? AND date>=?", (cid, today.isoformat())).fetchone()
    return dict(available=True, window=[start.isoformat(), end.isoformat()], observed_mm=round(obs, 1), normal_mm=round(normal, 1), years_used=len(clim),
                anomaly=round(obs / normal - 1, 3) if normal > 0 else None, confidence="LOW" if normal < 30 else "OK",
                forecast_7d_mm=round(f[0], 1) if f[0] is not None else None, forecast_fetched_at=f[1],
                source="Open-Meteo ERA5 reanalysis (history) + model forecast; not station gauges", status="REAL (modelled reanalysis)")

# ---- more real, keyless sources (docs: open-meteo.com/en/docs, open-meteo.com/en/docs/flood-api, power.larc.nasa.gov/docs/services/api/) ----
FCW = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration&forecast_days=7&timezone=auto"
ARW = "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={a}&end_date={b}&daily=temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration&timezone=auto"
FLD = "https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lon}&daily=river_discharge&past_days=30&forecast_days=7"
NP = "https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR&community=AG&longitude={lon}&latitude={lat}&start={a}&end={b}&format=JSON"
def due(ds, cid, secs=86400):
    r = conn().execute("SELECT MAX(ts) FROM data_ingestion_logs WHERE dataset=? AND city_id=? AND ok=1", (ds, cid)).fetchone()[0]
    return not r or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(r)).total_seconds() > secs
def _run(ds, cid, src, fn):
    rec = valid = 0; err = None
    try: rec, valid = fn()
    except Exception as e: err = str(e)[:200]
    _log(ds, cid, rec, valid, err, src); return err is None
def _weather(kind, url, cid, c, **kw):
    def go():
        d = _get(url.format(**c, **kw))["daily"]; rows = list(zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], d["et0_fao_evapotranspiration"])); valid = 0
        with LOCK:
            db = conn()
            for day, tx, tn, et in rows:
                if None in (tx, tn, et) or not (-30 <= tn <= tx <= 60) or not (0 <= et < 30): continue
                db.execute("INSERT OR REPLACE INTO weather_daily VALUES(?,?,?,?,?,?,?)", (cid, day, kind, tx, tn, et, now())); valid += 1
            db.commit()
        return len(rows), valid
    return go
def ingest_weather_forecast(cid, c): return _run("daily weather forecast", cid, "open-meteo", _weather("forecast", FCW, cid, c))
def ingest_weather_history(cid, c, today=None):
    t = today or dt.date.today(); return _run("daily weather archive", cid, "open-meteo", _weather("history", ARW, cid, c, a=t - dt.timedelta(days=400), b=t - dt.timedelta(days=5)))
def ingest_flood(cid, c):
    def go():
        d = _get(FLD.format(**c))["daily"]; rows = list(zip(d["time"], d["river_discharge"])); valid = 0
        with LOCK:
            db = conn()
            for day, v in rows:
                if v is None or not (0 <= v < 1e7): continue
                db.execute("INSERT OR REPLACE INTO river_discharge VALUES(?,?,?,?)", (cid, day, v, now())); valid += 1
            db.commit()
        return len(rows), valid
    return _run("river discharge (GloFAS)", cid, "Open-Meteo Flood API", go)
def ingest_nasa(cid, c, today=None):
    t = today or dt.date.today()
    def go():
        p = _get(NP.format(a=(t - dt.timedelta(days=35)).strftime("%Y%m%d"), b=(t - dt.timedelta(days=3)).strftime("%Y%m%d"), **c))["properties"]["parameter"]["PRECTOTCORR"]; valid = 0
        with LOCK:
            db = conn()
            for k, v in p.items():
                if v is None or not (0 <= v < 1000): continue
                db.execute("INSERT OR REPLACE INTO nasa_rain VALUES(?,?,?,?)", (cid, f"{k[:4]}-{k[4:6]}-{k[6:]}", v, now())); valid += 1
            db.commit()
        return len(p), valid
    return _run("NASA POWER rainfall", cid, "NASA POWER", go)
def signals(cid, today=None):
    today = today or dt.date.today(); db = conn(); iso = today.isoformat(); out = {}
    r = db.execute("SELECT date,tmax,tmin FROM weather_daily WHERE city_id=? AND kind='forecast' AND date>=? ORDER BY date LIMIT 1", (cid, iso)).fetchone()
    out["temp"] = dict(date=r["date"], tmax=round(r["tmax"], 1), tmin=round(r["tmin"], 1)) if r else None
    r = db.execute("SELECT SUM(et0) s,MAX(date) b,COUNT(*) n FROM weather_daily WHERE city_id=? AND kind='forecast' AND date>=?", (cid, iso)).fetchone()
    out["et0"] = dict(mm_7d=round(r["s"], 1), to=r["b"]) if r and r["n"] else None
    past = [x for x in db.execute("SELECT date,m3s FROM river_discharge WHERE city_id=? ORDER BY date", (cid,)).fetchall() if x["date"] <= iso]
    if past:
        last = past[-1]; w = past[-30:]; mean = sum(x["m3s"] for x in w) / len(w)
        out["river"] = dict(date=last["date"], latest_m3s=round(last["m3s"], 1), mean30_m3s=round(mean, 1), change_pct=round((last["m3s"] / mean - 1) * 100) if mean > 0 else None)
    else: out["river"] = None
    a = db.execute("SELECT MAX(date) FROM rainfall_observations WHERE city_id=?", (cid,)).fetchone()[0]; b = db.execute("SELECT MAX(date) FROM nasa_rain WHERE city_id=?", (cid,)).fetchone()[0]
    out["crosscheck"] = None
    if a and b:
        end = dt.date.fromisoformat(min(a, b)); start = end - dt.timedelta(days=29)
        q = lambda t: db.execute(f"SELECT SUM(precip_mm),COUNT(*) FROM {t} WHERE city_id=? AND date BETWEEN ? AND ?", (cid, start.isoformat(), end.isoformat())).fetchone()
        (so, no), (sn, nn) = q("rainfall_observations"), q("nasa_rain")
        if no >= 25 and nn >= 25:
            out["crosscheck"] = dict(window=f"{start.isoformat()} to {end.isoformat()}", openmeteo_mm=round(so, 1), nasa_mm=round(sn, 1), agreement_pct=round(100 - abs(so - sn) / max(so, sn, 1) * 100, 1))
    return out
