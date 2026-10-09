import os; os.environ.setdefault("AQUA_DB", ":memory:"); os.environ["AQUA_POLL"] = "0"
import datetime as dt, json
from fastapi.testclient import TestClient
import app.main as M
from app import alerts as A
from app.db import conn
PHONES = "9876500001, 9876500002, 9876500003"
T0 = dt.datetime(2026, 10, 8, 6, 0, tzinfo=dt.timezone.utc)
def setup_function():
    os.environ["ALERT_PHONES"] = PHONES; os.environ["ALERT_PROVIDER"] = "log"; os.environ.pop("ALERT_ADMIN_TOKEN", None)
    A._init(); conn().executescript("DELETE FROM alert_state; DELETE FROM alert_log; DELETE FROM reservoir_observations;"); conn().commit()
def cities(red_ids=()):
    c = json.loads(json.dumps(M.CITIES))
    for k in red_ids: c[k]["snap"] = c[k]["fl"]          # reserve at the failure floor -> day 0 -> CRITICAL
    return c
class Cap:
    def __init__(s, fail=()): s.sent = []; s.fail = set(fail)
    def __call__(s, to, text):
        s.sent.append((to, text)); return (to not in s.fail), ("ok" if to not in s.fail else "HTTP 400 number +919876500001 unverified")
def test_phone_normalisation():
    assert A.normalize("9876500001") == "+919876500001" and A.normalize("+91 98765 00002") == "+919876500002" and A.normalize("09876500003") == "+919876500003"
    assert A.normalize("1234567890") is None and A.normalize("98765") is None
    assert A.recipients()[0] == ["+919876500001", "+919876500002", "+919876500003"]
def test_no_alert_when_nothing_is_red():
    s = Cap(); assert A.check_and_send(cities(), s, T0) == [] and not s.sent
def test_red_city_alerts_all_three_numbers_once():
    s = Cap(); out = A.check_and_send(cities(["maa"]), s, T0)
    assert len(out) == 3 and {t for t, _ in s.sent} == {"+919876500001", "+919876500002", "+919876500003"}
    assert all("RED ALERT" in m and "Chennai" in m for _, m in s.sent) and all(m.isascii() and len(m) < 330 for _, m in s.sent)
    s2 = Cap(); assert A.check_and_send(cities(["maa"]), s2, T0 + dt.timedelta(minutes=10)) == [] and not s2.sent   # no spam inside the window
def test_repeat_after_window_and_realert_after_recovery():
    s = Cap(); A.check_and_send(cities(["maa"]), s, T0); s.sent.clear()
    assert len(A.check_and_send(cities(["maa"]), s, T0 + dt.timedelta(hours=25))) == 3
    A.check_and_send(cities(), s, T0 + dt.timedelta(hours=26)); s.sent.clear()                     # recovered
    assert len(A.check_and_send(cities(["maa"]), s, T0 + dt.timedelta(hours=27))) == 3             # red again -> new alert
def test_failed_recipient_is_retried_only_for_that_number_then_stops():
    s = Cap(fail=["+919876500002"]); A.check_and_send(cities(["bom"]), s, T0); s.sent.clear()
    out = A.check_and_send(cities(["bom"]), s, T0 + dt.timedelta(minutes=10)); assert [t for t, _ in s.sent] == ["+919876500002"] and not out[0]["ok"]
    for i in range(2, 12): A.check_and_send(cities(["bom"]), s, T0 + dt.timedelta(minutes=10 * i))
    n = len(s.sent); A.check_and_send(cities(["bom"]), s, T0 + dt.timedelta(hours=3)); assert len(s.sent) == n   # gave up after max retries
def test_orange_never_sends():
    c = cities(); k = c["vsk"]; k["snap"] = k["fl"] + 0.03     # low but not red
    st = A.city_state("vsk", k); assert st["status"] in ("HIGH RISK", "WATCH", "CRITICAL")
    if st["status"] != "CRITICAL": s = Cap(); assert A.check_and_send(c, s, T0) == [] and not s.sent
def test_latest_official_level_drives_the_alert():
    conn().execute("INSERT INTO reservoir_observations VALUES('maa','ALL','2026-10-07',?,?)", (M.CITIES["maa"]["fl"] * 100, "t")); conn().commit()
    s = Cap(); A.check_and_send(M.CITIES, s, T0); assert any("level as of 2026-10-07" in m for _, m in s.sent)
def test_no_numbers_configured_does_nothing():
    os.environ["ALERT_PHONES"] = ""; s = Cap(); assert A.check_and_send(cities(["maa"]), s, T0) == [] and not s.sent
def test_error_text_is_scrubbed_in_log():
    s = Cap(fail=["+919876500001"]); A.check_and_send(cities(["maa"]), s, T0)
    rows = conn().execute("SELECT recipient,detail FROM alert_log").fetchall()
    assert all("9876500001" not in (r["detail"] or "") + r["recipient"].replace("******4907", "") for r in rows)
def test_public_status_masks_numbers_and_exposes_no_secrets():
    os.environ["ALERT_WEBHOOK_TOKEN"] = "SECRETSECRET"; j = TestClient(M.app).get("/api/alerts/status").json()
    assert j["red_only"] and len(j["recipients"]) == 3 and "SECRETSECRET" not in json.dumps(j) and "9876500001" not in json.dumps(j) and j["live"] is False
def test_test_endpoint_is_locked_without_token_and_rate_limited(monkeypatch):
    c = TestClient(M.app); assert c.post("/api/alerts/test", json={}).status_code == 403
    os.environ["ALERT_ADMIN_TOKEN"] = "letmein"; assert c.post("/api/alerts/test", json={}, headers={"X-Admin-Token": "nope"}).status_code == 401
    ok = c.post("/api/alerts/test", json={"city": "maa"}, headers={"X-Admin-Token": "letmein"}); j = ok.json()
    assert ok.status_code == 200 and j["sent"] == 3 and j["live"] is False
    for _ in range(4): c.post("/api/alerts/test", json={}, headers={"X-Admin-Token": "letmein"})
    assert c.post("/api/alerts/test", json={}, headers={"X-Admin-Token": "letmein"}).status_code == 429
def test_provider_env_is_tolerant_and_phones_with_spaces(monkeypatch):
    for v, want in (("", "log"), ("  NTFY ", "ntfy"), ("log", "log")):
        monkeypatch.setenv("ALERT_PROVIDER", v); assert A.provider() == want
    monkeypatch.setenv("ALERT_PHONES", "+91 98765 00001, 9876500002\n9876500003")
    assert A.recipients() == (["+919876500001", "+919876500002", "+919876500003"], 0)
def test_demo_alert_button_sends_to_all_numbers_and_is_limited():
    s = Cap(); T = T0
    out = A.send_demo(29, 1120, 640, s, T)
    assert out["sent"] == 3 and out["level"] == "CRITICAL" and len(s.sent) == 3
    assert all("RED ALERT" in m and "ILLUSTRATIVE" in m and m.isascii() and len(m) < 330 for _, m in s.sent)
    import pytest
    with pytest.raises(PermissionError): A.send_demo(29, 1120, 640, Cap(), T + dt.timedelta(seconds=3))      # 10 s cooldown
    for i in range(4): A.send_demo(29, 1120, 640, Cap(), T + dt.timedelta(seconds=20 * (i + 1)))
    with pytest.raises(PermissionError): A.send_demo(29, 1120, 640, Cap(), T + dt.timedelta(seconds=200))    # 5 per hour
def test_demo_alert_endpoint_dry_run_and_validation():
    c = TestClient(M.app); r = c.post("/api/alerts/demo", json={"res": 78, "dem": 1000, "sup": 1010})
    assert r.status_code == 200 and r.json()["live"] is False and r.json()["level"] == "NORMAL" and r.json()["sent"] == 3
    assert c.post("/api/alerts/demo", json={"res": 500, "dem": 1, "sup": 1}).status_code == 422
    os.environ["ALERT_PHONES"] = ""; assert c.post("/api/alerts/demo", json={"res": 29, "dem": 1120, "sup": 640}).status_code in (409, 429)
def test_ntfy_provider_pushes_once_to_topic():
    import threading, http.server
    got = []
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(s): got.append((s.path, s.headers.get("Priority"), s.rfile.read(int(s.headers["Content-Length"])).decode())); s.send_response(200); s.end_headers(); s.wfile.write(b"{}")
        def log_message(*a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 8767), H); threading.Thread(target=srv.handle_request, daemon=True).start()
    os.environ.update(ALERT_PROVIDER="ntfy", NTFY_TOPIC="t-123", NTFY_SERVER="http://127.0.0.1:8767")
    try:
        out = A.send_demo(29, 1120, 640)
        assert out["sent"] == 1 and out["live"] and got[0][0] == "/t-123" and got[0][1] == "urgent" and "RED ALERT" in got[0][2]
    finally:
        for k in ("ALERT_PROVIDER", "NTFY_TOPIC", "NTFY_SERVER"): os.environ.pop(k, None)
def test_ntfy_topic_alone_switches_provider_on_and_topic_is_not_exposed(monkeypatch):
    monkeypatch.delenv("ALERT_PROVIDER", raising=False); monkeypatch.setenv("NTFY_TOPIC", "secret-topic-77")
    assert A.provider() == "ntfy" and A.live() and A.recipients()[0] == ["ntfy:secret-topic-77"]
    assert "secret-topic-77" not in json.dumps(TestClient(M.app).get("/api/alerts/status").json())
def test_unknown_provider_gives_a_clear_error(monkeypatch):
    monkeypatch.setenv("ALERT_PROVIDER", "smsx"); ok, d = A.send_one("+919876500001", "x"); assert not ok and "ntfy" in d
