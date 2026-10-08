import os; os.environ["AQUA_DB"] = ":memory:"; os.environ["AQUA_POLL"] = "0"
from fastapi.testclient import TestClient
import app.main as M
from app import engine as E
c = TestClient(M.app)
def test_cities(): assert {x["id"] for x in c.get("/api/cities").json()} >= {"vsk", "maa", "bom"}
def test_unknown_city(): assert c.get("/api/cities/zzz/water-status").status_code == 404
def test_validation(): assert c.post("/api/simulation", json={"city": "vsk", "levers": {"con": 99}}).status_code == 422
def test_scenarios_move_horizon():
    k = M.CITIES["maa"]; assert E.horizon(k, E.params(k, "drought")) <= E.horizon(k, E.params(k, "normal"))
def test_optimizer_respects_limits_and_helps():
    k = M.CITIES["maa"]; o = E.optimize(k, E.params(k, "crisis"))
    assert o["horizon_after"] >= o["horizon_before"] and o["plan"]["ind"] >= 60 and o["plan"]["con"] <= 30

def test_compat_simulate_matches_engine():
    k = M.CITIES["vsk"]; p = E.params(k, "crisis")
    assert c.post("/api/simulate", json={"city": "vsk", "params": p}).json()["day"] == E.simulate(k, p)["day"]
import datetime as dt, app.ingest as I
def _fake(u):
    if "archive" in u:
        t = dt.date(2026, 10, 8); n = (t - dt.timedelta(5) - dt.date(2021, 1, 1)).days + 1
        days = [(dt.date(2021, 1, 1) + dt.timedelta(d)).isoformat() for d in range(n)]
        return {"daily": {"time": days, "precipitation_sum": [5.0 if d >= "2026-09" else 10.0 for d in days]}}
    return {"daily": {"time": ["2026-10-08", "2026-10-09"], "precipitation_sum": [1.0, None]}}
def test_ingest_validates_and_rain_signal(monkeypatch):
    monkeypatch.setattr(I, "_get", _fake); k = M.CITIES["vsk"]
    assert I.ingest_forecast("vsk", k) and I.ingest_history("vsk", k, dt.date(2026, 10, 8))
    s = I.rain_signal("vsk", dt.date(2026, 10, 8))
    assert s["available"] and round(s["anomaly"], 2) == -0.5 and s["confidence"] == "OK"
    h = c.get("/api/data-health").json(); f = [d for d in h["datasets"] if "forecast" in d["dataset"]][0]
    assert f["status"] == "CONNECTED" and f["rejected"] == 1
def test_failure_is_reported_not_hidden(monkeypatch):
    def boom(u): raise OSError("network down")
    monkeypatch.setattr(I, "_get", boom); assert not I.ingest_forecast("kak", M.CITIES["kak"])
    f = [d for d in c.get("/api/data-health").json()["datasets"] if "forecast" in d["dataset"]][0]
    assert f["status"] == "DEGRADED" and "network down" in f["last_error"]
def test_rain_signal_unavailable_before_ingest(): assert c.get("/api/cities/maa/rain-signal").json()["available"] is False

def test_upload_validates_and_feeds_health():
    good = "city,reservoir,date,storage_pct\nmaa,ALL,2026-07-23,44.31\nmaa,Poondi,2026-07-23,31\n"
    bad = "zzz,ALL,2026-07-23,40\nmaa,ALL,2999-01-01,40\nmaa,ALL,2026-07-23,140\n"
    r = c.post("/api/reservoir-levels", json={"csv": good + bad}).json()
    assert r["accepted"] == 2 and r["rejected"] == 3
    assert c.get("/api/cities/maa/levels/latest").json()["storage_pct"] == 44.31
    h = [d for d in c.get("/api/data-health").json()["datasets"] if "upload" in d["dataset"]][0]
    assert h["status"] == "CONNECTED" and h["rejected"] == 3
def test_upload_rejects_bad_header(): assert c.post("/api/reservoir-levels", json={"csv": "a,b\n1,2"}).status_code == 422

import app.ingest as I3
def _fake3(u):
    t = dt.date(2026, 10, 8)
    if "precipitation_sum" in u: return _fake(u)
    if "flood-api" in u:
        days = [(t + dt.timedelta(d)).isoformat() for d in range(-30, 8)]; return {"daily": {"time": days, "river_discharge": [100.0 + i for i in range(len(days))]}}
    if "power.larc" in u:
        days = [t - dt.timedelta(d) for d in range(35, 2, -1)]; return {"properties": {"parameter": {"PRECTOTCORR": {d.strftime("%Y%m%d"): (5.0 if d.day != 5 else -999) for d in days}}}}
    n = 7 if "forecast_days" in u else 400; s = t if "forecast_days" in u else t - dt.timedelta(405)
    days = [(s + dt.timedelta(d)).isoformat() for d in range(n)]
    return {"daily": {"time": days, "temperature_2m_max": [35.0] * n, "temperature_2m_min": [25.0] * n, "et0_fao_evapotranspiration": [5.0] * n}}
def test_more_sources_signals_and_health(monkeypatch):
    monkeypatch.setattr(I3, "_get", _fake3); k = M.CITIES["vsk"]; today = dt.date(2026, 10, 8)
    assert I3.ingest_history("vsk", k, today) and I3.ingest_weather_forecast("vsk", k) and I3.ingest_weather_history("vsk", k, today) and I3.ingest_flood("vsk", k) and I3.ingest_nasa("vsk", k, today)
    s = I3.signals("vsk", today)
    assert s["temp"]["tmax"] == 35.0 and s["et0"]["mm_7d"] == 35.0 and s["river"]["latest_m3s"] > 0
    assert 96 <= s["crosscheck"]["agreement_pct"] <= 97.5
    ds = {d["dataset"]: d for d in c.get("/api/data-health").json()["datasets"]}
    assert ds["river discharge (GloFAS)"]["status"] == "CONNECTED" and ds["river discharge (GloFAS)"]["data_through"] == "2026-10-15"
    assert ds["NASA POWER rainfall"]["rejected"] >= 1 and ds["NASA POWER rainfall"]["status"] == "CONNECTED"
def test_new_source_failure_is_visible(monkeypatch):
    def boom(u): raise OSError("flood api down")
    monkeypatch.setattr(I3, "_get", boom); assert not I3.ingest_flood("kak", M.CITIES["kak"])
    d = {x["dataset"]: x for x in c.get("/api/data-health").json()["datasets"]}["river discharge (GloFAS)"]
    assert d["status"] == "DEGRADED" and "flood api down" in d["last_error"]
def test_signals_endpoint_unknown_city(): assert c.get("/api/cities/zzz/signals").status_code == 404
