"""Pre-demo check: is the backend up, is every data feed really LIVE, and is the ML report present?
  python scripts/preflight.py                      # checks http://localhost:8000
  python scripts/preflight.py https://your-app.onrender.com
Prints PASS / WARN / FAIL per item with the real error text, and exits 1 if anything FAILs. Run it 10 minutes before the demo and again on the venue network.
It only reads status endpoints; it sends no alerts."""
import sys, json, time, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
fails = warns = 0
def get(path, timeout=40):
    t = time.time(); r = urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": "aquaforecast-preflight"}), timeout=timeout)
    return json.loads(r.read()), time.time() - t
def say(level, msg):
    global fails, warns
    fails += level == "FAIL"; warns += level == "WARN"; print(f"{level:5} {msg}")

try:
    j, dt_ = get("/api/cities"); say("PASS", f"backend reachable, {len(j)} cities, {dt_:.1f}s")
    if dt_ > 10: say("WARN", "slow first response: a sleeping free-tier host? open the site once before presenting")
except Exception as e:
    say("FAIL", f"backend not reachable at {BASE}: {e}"); sys.exit(1)

try:
    h, _ = get("/api/data-health"); rows = h["datasets"]
    live = [r for r in rows if r["status"] == "CONNECTED"]; say("PASS" if len(live) >= 6 else "WARN", f"{len(live)} of {len(rows)} datasets CONNECTED (poll every {h['poll_seconds']} s)")
    for r in rows:
        if r["status"] == "CONNECTED": continue
        manual = r["dataset"].startswith(("reservoir levels (upload)", "government"))
        lvl = "WARN" if (manual or r["status"] == "NO SYNC YET") else "FAIL"
        say(lvl, f"{r['dataset']}: {r['status']}" + (f" | {r['last_error']}" if r.get("last_error") else "") + (" (needs a file/URL you provide)" if manual else ""))
except Exception as e: say("FAIL", f"/api/data-health: {e}")

try:
    c, _ = get("/api/cwc-feed"); s = c.get("status"); say("PASS" if s in ("UPDATED", "UNCHANGED") else "FAIL", f"CWC bulletin feed: {s}, bulletin {c.get('bulletin_date')}, {c.get('records')} reservoirs" + (f" | {c['error']}" if c.get("error") else ""))
    if c.get("bulletin_date"):
        import datetime as dt
        age = (dt.date.today() - dt.date.fromisoformat(c["bulletin_date"])).days
        if age > 10: say("WARN", f"bulletin is {age} days old: CWC publishes weekly; upload the newest PDF to the shared link")
except Exception as e: say("FAIL", f"/api/cwc-feed: {e}")

try:
    a, _ = get("/api/alerts/status"); say("PASS", "alerts endpoint ok") ; print("      ", json.dumps({k: a[k] for k in a if k in ("provider", "mode", "red_only", "recipients", "admin_token_set")})[:200])
    if str(a.get("provider", "log")).lower() in ("log", ""): say("WARN", "ALERT_PROVIDER=log: dry run, nothing will be delivered. Set a real provider to show a live SMS/WhatsApp")
except Exception as e: say("WARN", f"/api/alerts/status: {e}")

try:
    m, _ = get("/api/ml/validation")
    if m.get("status") == "OK": say("PASS", f"ML report: {m['data']['bulletin_dates']} bulletin dates, {m['data']['reservoirs']} reservoirs, source {m['data_source']}")
    else: say("WARN", f"ML report: {m.get('status')}. {m.get('message', '')}")
    if m.get("data_source") == "SYNTHETIC": say("FAIL", "the served ML report is SYNTHETIC: remove data/ml_report.json and rerun scripts/run_backtest.py on real history")
except Exception as e: say("FAIL", f"/api/ml/validation: {e}")

print(f"\n{'READY' if not fails else 'NOT READY'}: {fails} fail, {warns} warn")
sys.exit(1 if fails else 0)
