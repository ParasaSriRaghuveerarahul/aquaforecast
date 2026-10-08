"""Open-Meteo connectors (public, keyless; https://open-meteo.com/en/docs). Forecast = model forecast; archive = ERA5-based
reanalysis (not rain-gauge data). Every run is validated and logged. No synthetic fallback: failures are recorded, not hidden."""
import json, urllib.request, datetime as dt
from .db import conn, LOCK
FC = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum&forecast_days=7&timezone=auto"
AR = "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={a}&end_date={b}&daily=precipitation_sum&timezone=auto"
def _get(u): return json.load(urllib.request.urlopen(u, timeout=20))
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def _log(dataset, cid, rec, valid, err):
    with LOCK:
        d = conn(); d.execute("INSERT INTO data_ingestion_logs(source,dataset,city_id,ts,records_received,records_valid,records_rejected,ok,error) VALUES(?,?,?,?,?,?,?,?,?)",
                              ("open-meteo", dataset, cid, now(), rec, valid, rec - valid, int(err is None), err)); d.commit()
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
    for cid, c in cities.items():
        ingest_forecast(cid, c)
        if history_due(cid): ingest_history(cid, c)
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
