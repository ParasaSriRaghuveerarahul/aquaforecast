import os, tempfile; os.environ["AQUA_DB"] = ":memory:"; os.environ["AQUA_POLL"] = "0"; _d = tempfile.mkdtemp(); os.environ["AQUA_GOVT_DROP"] = _d
import pathlib, datetime as dt
from fastapi.testclient import TestClient
import app.main as M, app.govt as G
c = TestClient(M.app); P = pathlib.Path(_d)
def feed(cid): return [f for f in c.get("/api/govt-feed").json()["feeds"] if f["city"] == cid][0]
def test_lists_every_city_not_configured_until_a_file_exists():
    fs = c.get("/api/govt-feed").json()["feeds"]; assert {f["city"] for f in fs} == set(M.CITIES) and all(f["cadence_days"] == 30 for f in fs)
    assert feed("hyd")["status"] == "NOT CONFIGURED"
def test_ingest_only_when_changed_then_picks_up_next_release():
    (P / "bom.csv").write_text("reservoir,date,storage_pct\nALL,2026-10-03,95.84\nBhatsa,2026-10-03,98.13\n")
    assert G.check_city("bom") == "UPDATED"; f = feed("bom")
    assert f["data_as_of"] == "2026-10-03" and f["level_pct"] == 95.84 and f["next_expected"] == "2026-11-02" and f["status"].startswith("UPDATED")
    changed = f["last_changed"]
    assert G.check_city("bom") == "UNCHANGED"; f = feed("bom")      # next 10-minute cycle: nothing new, nothing re-ingested
    assert f["last_changed"] == changed and f["status"].startswith("UP TO DATE") and f["last_checked"] >= changed
    (P / "bom.csv").write_text("reservoir,date,storage_pct\nALL,2026-10-03,95.84\nALL,2026-10-07,93.10\n")   # department publishes a new release
    assert G.check_city("bom") == "UPDATED"; f = feed("bom"); assert f["data_as_of"] == "2026-10-07" and f["level_pct"] == 93.1
    assert c.get("/api/cities/bom/levels/latest").json()["storage_pct"] == 93.1
def test_bad_rows_rejected_and_bad_header_fails_without_losing_old_data():
    (P / "maa.csv").write_text("reservoir,date,storage_pct\nALL,2026-10-01,44.31\nPoondi,2026-10-01,150\nPuzhal,2999-01-01,10\n")
    assert G.check_city("maa") == "UPDATED"; f = feed("maa"); assert f["level_pct"] == 44.31 and "outside 0-100" in f["error"]
    (P / "maa.csv").write_text("name,pct\nx,1\n"); assert G.check_city("maa") == "FAILED"
    f = feed("maa"); assert f["status"] == "FAILED" and f["data_as_of"] == "2026-10-01" and f["level_pct"] == 44.31
def test_visible_in_data_health_and_manual_check_endpoint():
    ds = [d for d in c.get("/api/data-health").json()["datasets"] if d["dataset"] == "government reservoir feed"][0]; assert ds["cities_ok"] >= 1
    assert c.post("/api/govt-feed/check").status_code == 200
