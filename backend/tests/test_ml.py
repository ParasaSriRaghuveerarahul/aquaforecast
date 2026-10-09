import os; os.environ["AQUA_DB"] = ":memory:"; os.environ["AQUA_POLL"] = "0"
import datetime as dt, json, pytest
from fastapi.testclient import TestClient
import app.main as M, app.ml as ml, app.cwc as W
from tests.test_cwc import T as BULLETIN
c = TestClient(M.app)

@pytest.fixture(scope="module")
def rep():
    return ml.backtest(ml.synthetic_rows(n_res=15, weeks=110), source="SYNTHETIC")

def test_fold_split_never_uses_the_future():
    P = ml.panel(ml.synthetic_rows(n_res=6, weeks=80)); S = ml.samples(P, 4); dates = sorted({s["d"] for s in S}); blk = dates[40:50]
    tr, te = ml.fold_split(S, blk); T = min(blk)
    assert tr and te and all(s["td"] <= T and s["d"] < T for s in tr) and all(s["d"] in set(blk) for s in te)
    assert not ({(s["res"], s["d"]) for s in tr} & {(s["res"], s["d"]) for s in te})

def test_refuses_to_report_with_too_little_history():
    r = ml.backtest(ml.synthetic_rows(n_res=10, weeks=30), source="SYNTHETIC")
    assert r["status"] == "INSUFFICIENT HISTORY" and r["horizons"] == {} and "backfill" in r["message"]

def test_report_has_baselines_intervals_and_event_counts(rep):
    assert rep["status"] == "OK" and rep["data_source"] == "SYNTHETIC" and set(rep["horizons"]) == {"1", "2", "4"}
    for h, o in rep["horizons"].items():
        assert o["status"] == "OK" and {"persistence", "linear_trend", "climatology_delta", "model"} <= set(o["methods"])
        assert o["methods"]["model"]["vs_best_baseline"]["baseline"] in ("linear_trend", "climatology_delta")
        assert len(o["methods"]["model"]["skill_ci95"]) == 2
        on = o["events"]["onset_only"]; assert on["n"] > 0 and "n_events" in on and "model_sensitive" in on["methods"]
    assert rep["feature_importance"]["4"] and rep["limits"]

def test_conformal_band_reaches_nominal_coverage_on_unseen_weeks(rep):
    for o in rep["horizons"].values():
        assert 0.72 <= o["interval"]["coverage"] <= 0.88
        assert o["interval"]["coverage"] >= o["interval"]["coverage_uncalibrated"] - 0.01

def test_model_beats_weak_baselines_on_seasonal_synthetic_data(rep):
    m = rep["horizons"]["4"]["methods"]; assert m["model"]["mae"] < m["persistence"]["mae"] and m["model"]["mae"] < m["linear_trend"]["mae"]

def test_same_data_gives_same_report():
    rows = ml.synthetic_rows(n_res=10, weeks=100, seed=9); a = ml.backtest(rows, n_folds=2, source="SYNTHETIC"); b = ml.backtest(rows, n_folds=2, source="SYNTHETIC")
    assert a["horizons"] == b["horizons"]

def test_api_says_not_run_when_no_real_report(monkeypatch, tmp_path):
    monkeypatch.setattr(ml, "REPORT_PATH", tmp_path / "none.json")
    assert c.get("/api/ml/validation").json()["status"] == "NOT RUN" and c.get("/api/ml/forecast").json()["forecasts"] == {}

def test_api_serves_report_and_forecast_bands(monkeypatch, tmp_path, rep):
    p = tmp_path / "r.json"; ml.write_report(rep, p); monkeypatch.setattr(ml, "REPORT_PATH", p)
    assert c.get("/api/ml/validation").json()["data_source"] == "SYNTHETIC"
    f = c.get("/api/ml/forecast", params=dict(reservoir="syn 03")).json()["forecasts"]["SYN 03"]["weeks"]["2"]
    assert 0 <= f["p10"] <= f["p50"] <= f["p90"] <= 100
    assert c.get("/api/ml/forecast", params=dict(reservoir="nope")).status_code == 404

def test_backfill_stores_history_without_touching_live_feed_status(monkeypatch):
    monkeypatch.setattr(W, "_pdf_text", lambda b: BULLETIN); W._init(); W.conn().execute("DELETE FROM cwc_reservoirs"); W.conn().execute("DELETE FROM cwc_feed"); W.conn().commit()
    d, n, rej = W.ingest_pdf(b"%PDF-1", today=dt.date(2026, 10, 9)); assert (d, n, rej) == ("2026-10-08", 122, 0)
    assert W.conn().execute("SELECT COUNT(*) FROM cwc_feed").fetchone()[0] == 0
    h = W.history_rows(); assert len(h) == 122 and {"reservoir", "date", "pct", "normal", "ly", "cap"} <= set(h[0])
    with pytest.raises(ValueError): W.ingest_pdf(b"<html>")
