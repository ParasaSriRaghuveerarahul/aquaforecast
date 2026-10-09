import os; os.environ["AQUA_DB"] = ":memory:"; os.environ["AQUA_POLL"] = "0"
import datetime as dt
from fastapi.testclient import TestClient
import app.main as M, app.cwc as W
c = TestClient(M.app)
ROWS = [("KRISHNARAJA\nSAGARA", "Karnataka", 1.163, .461, 39.64), ("KABINI", "Karnataka", .444, .197, 44.37)] + [(f"DAM {chr(65+i%26)}{chr(65+i//26)}", "Madhya\nPradesh", 1, .5, 50.0) for i in range(120)]
T = "WEEKLY REPORT OF 178 IMPORTANT RESERVOIRS OF INDIA 08.10.2026 " + "".join(f"{i} {n} {s} 0.000 60.000 320.040 {cap:.3f} 08.10.2026 299.634 {st:.3f} {p:.2f} 319.872 0.094 99.32 0.068 71.85 0.00 0.00\n" for i, (n, s, cap, st, p) in enumerate(ROWS, 1))
def feed(monkeypatch, body=b"%PDF-1", text=T):
    monkeypatch.setattr(W, "url", lambda: "https://example.test/b.pdf"); monkeypatch.setattr(W, "_fetch", lambda u: body); monkeypatch.setattr(W, "_pdf_text", lambda b: text)
def test_parse_reads_names_states_and_numbers():
    r, e = W.parse(T, dt.date(2026, 10, 9)); k = [x for x in r if x["reservoir"] == "KRISHNARAJA SAGARA"][0]
    assert len(r) == 122 and not e and k["pct"] == 39.64 and k["state"] == "Karnataka" and k["date"] == "2026-10-08"
def test_updates_then_unchanged_and_health_goes_connected(monkeypatch):
    feed(monkeypatch); assert W.check(force=True) == "UPDATED"; s = c.get("/api/cwc-feed").json()
    assert s["bulletin_date"] == "2026-10-08" and s["bengaluru_pct"] == round((.461 + .197) / (1.163 + .444) * 100, 2) and s["levels"]["KABINI"] == 44.37 and len(s["reservoirs"]) == 122 and ["KABINI", "Karnataka", 44.37, 99.32, 71.85] in s["reservoirs"]
    h = [d for d in c.get("/api/data-health").json()["datasets"] if d["dataset"] == W.DATASET][0]; assert h["status"] == "CONNECTED" and h["data_through"] == "2026-10-08"
    assert W.check(force=True) == "UNCHANGED"
def test_failures_are_reported_not_hidden(monkeypatch):
    feed(monkeypatch, body=b"<html>sign in</html>"); W._init(); W.conn().execute("DELETE FROM cwc_feed"); W.conn().commit()
    assert W.check(force=True) == "FAILED" and "not a PDF" in c.get("/api/cwc-feed").json()["error"]
