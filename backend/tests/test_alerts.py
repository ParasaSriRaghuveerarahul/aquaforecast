import os; os.environ.setdefault("AQUA_DB", ":memory:"); os.environ["AQUA_POLL"] = "0"
import datetime as dt, json
from fastapi.testclient import TestClient
import app.main as M
from app import alerts as A
from app.db import conn
PHONES = "9381244907, 6304534629, 9440678746"
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
        s.sent.append((to, text)); return (to not in s.fail), ("ok" if to not in s.fail else "HTTP 400 number +919381244907 unverified")
def test_phone_normalisation():
    assert A.normalize("9381244907") == "+919381244907" and A.normalize("+91 63045 34629") == "+916304534629" and A.normalize("09440678746") == "+919440678746"
    assert A.normalize("1234567890") is None and A.normalize("98765") is None
    assert A.recipients()[0] == ["+919381244907", "+916304534629", "+919440678746"]
def test_no_alert_when_nothing_is_red():
    s = Cap(); assert A.check_and_send(cities(), s, T0) == [] and not s.sent
def test_red_city_alerts_all_three_numbers_once():
    s = Cap(); out = A.check_and_send(cities(["maa"]), s, T0)
    assert len(out) == 3 and {t for t, _ in s.sent} == {"+919381244907", "+916304534629", "+919440678746"}
    assert all("RED ALERT" in m and "Chennai" in m for _, m in s.sent) and all(m.isascii() and len(m) < 330 for _, m in s.sent)
    s2 = Cap(); assert A.check_and_send(cities(["maa"]), s2, T0 + dt.timedelta(minutes=10)) == [] and not s2.sent   # no spam inside the window
def test_repeat_after_window_and_realert_after_recovery():
    s = Cap(); A.check_and_send(cities(["maa"]), s, T0); s.sent.clear()
    assert len(A.check_and_send(cities(["maa"]), s, T0 + dt.timedelta(hours=25))) == 3
    A.check_and_send(cities(), s, T0 + dt.timedelta(hours=26)); s.sent.clear()                     # recovered
    assert len(A.check_and_send(cities(["maa"]), s, T0 + dt.timedelta(hours=27))) == 3             # red again -> new alert
def test_failed_recipient_is_retried_only_for_that_number_then_stops():
    s = Cap(fail=["+916304534629"]); A.check_and_send(cities(["bom"]), s, T0); s.sent.clear()
    out = A.check_and_send(cities(["bom"]), s, T0 + dt.timedelta(minutes=10)); assert [t for t, _ in s.sent] == ["+916304534629"] and not out[0]["ok"]
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
    s = Cap(fail=["+919381244907"]); A.check_and_send(cities(["maa"]), s, T0)
    rows = conn().execute("SELECT recipient,detail FROM alert_log").fetchall()
    assert all("9381244907" not in (r["detail"] or "") + r["recipient"].replace("******4907", "") for r in rows)
def test_public_status_masks_numbers_and_exposes_no_secrets():
    os.environ["TWILIO_AUTH_TOKEN"] = "SECRETSECRET"; j = TestClient(M.app).get("/api/alerts/status").json()
    assert j["red_only"] and len(j["recipients"]) == 3 and "SECRETSECRET" not in json.dumps(j) and "9381244907" not in json.dumps(j) and j["live"] is False
def test_test_endpoint_is_locked_without_token_and_rate_limited(monkeypatch):
    c = TestClient(M.app); assert c.post("/api/alerts/test", json={}).status_code == 403
    os.environ["ALERT_ADMIN_TOKEN"] = "letmein"; assert c.post("/api/alerts/test", json={}, headers={"X-Admin-Token": "nope"}).status_code == 401
    ok = c.post("/api/alerts/test", json={"city": "maa"}, headers={"X-Admin-Token": "letmein"}); j = ok.json()
    assert ok.status_code == 200 and j["sent"] == 3 and j["live"] is False
    for _ in range(4): c.post("/api/alerts/test", json={}, headers={"X-Admin-Token": "letmein"})
    assert c.post("/api/alerts/test", json={}, headers={"X-Admin-Token": "letmein"}).status_code == 429
def test_twilio_request_shape(monkeypatch):
    seen = {}
    class R:  # fake HTTP response
        def read(s): return b'{"sid":"SM123456789012345"}'
    def fake(req, timeout=0): seen["u"] = req.full_url; seen["b"] = req.data.decode(); seen["a"] = req.headers.get("Authorization"); return R()
    monkeypatch.setattr(A.urllib.request, "urlopen", fake)
    for k, v in dict(ALERT_PROVIDER="twilio_sms", TWILIO_ACCOUNT_SID="ACx", TWILIO_AUTH_TOKEN="tok", TWILIO_FROM="+15550001111").items(): os.environ[k] = v
    ok, d = A.send_one("+919381244907", "hi"); assert ok and "Accounts/ACx/Messages.json" in seen["u"] and "To=%2B919381244907" in seen["b"] and "From=%2B15550001111" in seen["b"] and seen["a"].startswith("Basic ")
    os.environ["ALERT_PROVIDER"] = "twilio_whatsapp"; os.environ["TWILIO_FROM"] = "+14155238886"; A.send_one("+919381244907", "hi")
    assert "To=whatsapp%3A%2B919381244907" in seen["b"] and "From=whatsapp%3A%2B14155238886" in seen["b"]
    os.environ["ALERT_PROVIDER"] = "log"
