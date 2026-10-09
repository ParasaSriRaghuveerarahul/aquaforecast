"""Red-alert SMS / WhatsApp notifications.
RED = the engine's CRITICAL level: projected supply-demand failure in under 14 days (same rule that colours the Alert Center red).
ONLY red sends. Watch / high-risk / normal never do. Safe by design:
  * one alert when a city ENTERS red, repeated at most every ALERT_REPEAT_HOURS (default 24) while it stays red;
  * recipients whose send failed are retried on the next poll cycles (max ALERT_MAX_RETRIES, default 6), then dropped until the next window;
  * every attempt is logged (numbers masked); provider errors are stored with phone numbers scrubbed;
  * ALERT_PROVIDER=log (default) is a dry run: nothing leaves the server until real provider keys are set;
  * the TEST endpoint needs ALERT_ADMIN_TOKEN and is limited to 5 sends per hour, so the public site cannot be used to spam the numbers.
Providers: ntfy (free phone push, no account) | webhook (any HTTP service: MSG91 / Fast2SMS / n8n / Make) | log (dry run)."""
import os, re, json, uuid, datetime as dt, urllib.request, urllib.parse, urllib.error
from . import engine as E
from .db import conn, LOCK

RED = "CRITICAL"
LABEL = {"log": "dry-run log (no provider configured)", "webhook": "custom webhook", "ntfy": "ntfy push notification (free)"}

def _now(): return dt.datetime.now(dt.timezone.utc)
def _env(k, d=""): return (os.environ.get(k) or d).strip()   # an empty or space-padded value counts as unset
def provider(): return (_env("ALERT_PROVIDER") or ("ntfy" if _env("NTFY_TOPIC") else "log")).lower()     # NTFY_TOPIC alone is enough to switch ntfy on
def _iso(t): return t.isoformat(timespec="seconds")
def _init():
    conn().executescript("""CREATE TABLE IF NOT EXISTS alert_state(city_id TEXT PRIMARY KEY,red INT,last_sent TEXT,pending TEXT,attempts INT);
    CREATE TABLE IF NOT EXISTS alert_log(id INTEGER PRIMARY KEY,ts TEXT,batch TEXT,city_id TEXT,kind TEXT,recipient TEXT,ok INT,detail TEXT);""")

def normalize(num):
    """Indian mobile (10 digits starting 6-9, optional 91 / 0 prefix) or any +E.164 number -> '+91XXXXXXXXXX'; else None."""
    s = str(num).strip(); d = re.sub(r"\D", "", s)
    if s.startswith("+"): return "+" + d if 8 <= len(d) <= 15 else None
    if len(d) == 11 and d[0] == "0": d = d[1:]
    if len(d) == 10 and d[0] in "6789": return "+91" + d
    if len(d) == 12 and d.startswith("91") and d[2] in "6789": return "+" + d
    return None
def recipients():
    if provider() == "ntfy" and _env("NTFY_TOPIC"): return ["ntfy:" + _env("NTFY_TOPIC")], 0     # one push topic; every phone subscribed to it gets the alert
    good, bad = [], 0
    for chunk in [x.strip() for x in re.split(r"[,;\n]+", os.environ.get("ALERT_PHONES", "")) if x.strip()]:
        n = normalize(chunk)
        for x in ([n] if n else [normalize(t) for t in chunk.split()] if len(chunk.split()) > 1 else [None]):
            if x and x not in good: good.append(x)
            elif not x: bad += 1
    return good, bad
def mask(n): return "ntfy topic (subscribed phones)" if n.startswith("ntfy:") else n[:3] + " ******" + n[-4:] if n.startswith("+") else n
def _scrub(t): return re.sub(r"\+?\d[\d\s-]{7,}\d", "[number]", str(t))[:160]

def live():
    p = provider(); g = _env
    if p == "webhook": return bool(g("ALERT_WEBHOOK_URL"))
    if p == "ntfy": return bool(g("NTFY_TOPIC"))
    return False

def send_one(to, text):
    """Returns (ok, detail). Never raises."""
    p = provider(); g = _env
    if p == "log": return True, "dry-run: ALERT_PROVIDER=log, nothing was sent"
    if not live(): return False, f"provider '{p}' is not set up (ntfy needs NTFY_TOPIC; webhook needs ALERT_WEBHOOK_URL)"
    try:
        if p == "ntfy":
            h = {"Title": "AQUAFORECAST RED ALERT" if "RED ALERT" in text else "AQUAFORECAST", "Priority": "urgent", "Tags": "rotating_light"}
            urllib.request.urlopen(urllib.request.Request(g("NTFY_SERVER", "https://ntfy.sh").rstrip("/") + "/" + urllib.parse.quote(g("NTFY_TOPIC")), text.encode(), h), timeout=15)
            return True, "pushed to ntfy topic"
        if p == "webhook":
            h = {"Content-Type": "application/json"}
            if g("ALERT_WEBHOOK_TOKEN"): h["Authorization"] = g("ALERT_WEBHOOK_TOKEN")
            urllib.request.urlopen(urllib.request.Request(g("ALERT_WEBHOOK_URL"), json.dumps({"to": to, "message": text, "source": "aquaforecast"}).encode(), h), timeout=15)
            return True, "webhook accepted"
        return False, f"unknown ALERT_PROVIDER '{p}': use ntfy, webhook or log"
    except urllib.error.HTTPError as e: return False, _scrub(f"HTTP {e.code} {e.reason}")
    except Exception as e: return False, _scrub(e)

def city_state(cid, c):
    """Current status of a city using the latest official/uploaded level if one exists, else the reported snapshot (same rule as the UI)."""
    snap, asof = c["snap"], None
    r = conn().execute("SELECT date,storage_pct FROM reservoir_observations WHERE city_id=? ORDER BY date DESC,(reservoir='ALL') DESC LIMIT 1", (cid,)).fetchone()
    if r: snap, asof = r["storage_pct"] / 100, r["date"]
    k = {**c, "snap": snap}; s = E.simulate(k, E.params(k, "now"))
    return dict(city=c["name"], status=E.status(s["day"]), day=s["day"], reserve=round(s["reserve_pct"][0], 1), deficit=round(s["demand"][0] - s["supply"][0]), asof=asof)

def red_message(st):
    basis = f"level as of {st['asof']}" if st["asof"] else "latest reported level"
    return (f"[AQUAFORECAST RED ALERT] {st['city']}: CRITICAL water stress. Reserve {st['reserve']}% ({basis}). "
            f"Projected supply-demand failure in {st['day']} days, deficit {st['deficit']} ML/day (modelled). Open the Command Center and start emergency allocation.")

def _deliver(db, cid, kind, targets, text, send, now, batch):
    fails = []; out = []
    for n in targets:
        ok, detail = send(n, text); out.append(dict(city=cid, to=mask(n), ok=bool(ok), detail=detail))
        db.execute("INSERT INTO alert_log(ts,batch,city_id,kind,recipient,ok,detail) VALUES(?,?,?,?,?,?,?)", (_iso(now), batch, cid, kind, mask(n), int(bool(ok)), _scrub(detail)))
        if not ok: fails.append(n)
    return fails, out

def check_and_send(cities, send=None, now=None):
    """Called every poll cycle. Returns the list of delivery attempts made this cycle (empty almost always)."""
    send = send or send_one; now = now or _now(); to, _ = recipients()
    if not to: return []
    repeat = dt.timedelta(hours=float(os.environ.get("ALERT_REPEAT_HOURS", "24"))); maxtry = int(os.environ.get("ALERT_MAX_RETRIES", "6")); res = []
    with LOCK:
        _init(); db = conn()
        for cid, c in cities.items():
            st = city_state(cid, c); red = st["status"] == RED
            row = db.execute("SELECT * FROM alert_state WHERE city_id=?", (cid,)).fetchone()
            if not red: db.execute("INSERT OR REPLACE INTO alert_state VALUES(?,?,?,?,?)", (cid, 0, None, "[]", 0)); continue
            was = bool(row and row["red"]); last = row["last_sent"] if row else None
            pend = json.loads(row["pending"] or "[]") if row else []; tries = row["attempts"] if row else 0
            fresh = (not was) or not last or (now - dt.datetime.fromisoformat(last)) >= repeat
            targets = to if fresh else [n for n in pend if n in to] if (pend and tries < maxtry) else []
            if targets:
                fails, out = _deliver(db, cid, "red", targets, red_message(st), send, now, _iso(now)); res += out
                last, tries, pend = (_iso(now), 1, fails) if fresh else (last, tries + 1, fails)
            db.execute("INSERT OR REPLACE INTO alert_state VALUES(?,?,?,?,?)", (cid, 1, last, json.dumps(pend), tries))
        db.commit()
    return res

def send_test(cities, cid=None, send=None, now=None):
    send = send or send_one; now = now or _now(); to, _ = recipients()
    if not to: raise ValueError("no valid numbers in ALERT_PHONES")
    with LOCK:
        _init(); db = conn()
        if db.execute("SELECT COUNT(DISTINCT batch) FROM alert_log WHERE kind='test' AND ts>?", (_iso(now - dt.timedelta(hours=1)),)).fetchone()[0] >= 5:
            raise PermissionError("test limit reached: 5 per hour")
        cid = cid if cid in cities else next(iter(cities)); st = city_state(cid, cities[cid])
        text = f"[AQUAFORECAST TEST] Alert delivery check for the control-room numbers. This is NOT a real alert. {st['city']} is currently {st['status']}."
        fails, out = _deliver(db, cid, "test", to, text, send, now, "test-" + uuid.uuid4().hex); db.commit()
    return dict(sent=len(out) - len(fails), failed=len(fails), provider=LABEL.get(provider(), "unknown"), live=live(), results=out)

# --- Red Alert Demo page: "Send alert" button. Generic numbers, labelled ILLUSTRATIVE; goes ONLY to the numbers in ALERT_PHONES. ---
DEMO_POOL = 30000; DEMO_ZONES = [("A", .55), ("B", .8), ("C", 1), ("D", 1.3), ("E", 1.8), ("F", 2.7)]
def demo_day(res, dem, sup):
    d = dem - sup
    if d <= 0: return None
    if res <= 15: return 0
    x = int((res - 15) / 100 * DEMO_POOL / d + 0.5)
    return None if x > 120 else x
def demo_message(res, dem, sup):
    day = demo_day(res, dem, sup); lvl = E.status(day); deficit = max(0, round(dem - sup))
    risky = ", ".join(z for z, m in DEMO_ZONES if day is not None and E.status(int(day * m + 0.5)) in ("HIGH RISK", "CRITICAL"))
    head = "RED ALERT - " if lvl == RED else ""
    fail = f"Projected supply-demand failure in {day} days." if day is not None else "No failure projected."
    return (f"[AQUAFORECAST DEMO ALERT - ILLUSTRATIVE] {head}{lvl}. Generic example city, not real data. Reserve {round(res)}%, deficit {deficit} ML/day. {fail}"
            + (f" Zones at risk: {risky}. Reply ACK to confirm receipt." if risky else "")), lvl

def send_demo(res, dem, sup, send=None, now=None):
    """Sends the demo page's own alert (text built here from three numbers, never free text) to ALERT_PHONES. Limited: 5 per hour, one per 10 s."""
    send = send or send_one; now = now or _now(); to, _ = recipients()
    if not to:
        if live(): raise ValueError("no recipients configured for this provider")
        to = ["(no recipient configured: dry run)"]          # dry run still works so the page can use its browser fallbacks (siren, notification, direct ntfy push)
    with LOCK:
        _init(); db = conn()
        if db.execute("SELECT COUNT(DISTINCT batch) FROM alert_log WHERE kind='demo' AND ts>?", (_iso(now - dt.timedelta(hours=1)),)).fetchone()[0] >= 5:
            raise PermissionError("demo limit reached: 5 sends per hour")
        if db.execute("SELECT COUNT(*) FROM alert_log WHERE kind='demo' AND ts>?", (_iso(now - dt.timedelta(seconds=10)),)).fetchone()[0]:
            raise PermissionError("please wait 10 seconds between sends")
        text, lvl = demo_message(res, dem, sup)
        fails, out = _deliver(db, "demo", "demo", to, text, send, now, "demo-" + uuid.uuid4().hex); db.commit()
    return dict(sent=len(out) - len(fails), failed=len(fails), provider=LABEL.get(provider(), "unknown"), live=live(), level=lvl, message=text, results=out)

def status_info(cities):
    to, bad = recipients(); p = provider()
    with LOCK:
        _init(); db = conn(); st = {r["city_id"]: r for r in db.execute("SELECT * FROM alert_state")}
        log = [dict(ts=r["ts"], city=r["city_id"], kind=r["kind"], to=r["recipient"], ok=bool(r["ok"]), detail=r["detail"]) for r in db.execute("SELECT * FROM alert_log ORDER BY id DESC LIMIT 12")]
        cs = []
        for cid, c in cities.items():
            s = city_state(cid, c); cs.append(dict(id=cid, city=s["city"], status=s["status"], horizon_days=s["day"], red=s["status"] == RED, last_alert=st[cid]["last_sent"] if cid in st else None))
    return dict(red_only=True, rule="CRITICAL = projected supply-demand failure in under 14 days", recipients=[mask(n) for n in to], invalid_numbers=bad,
                provider=p, provider_label=LABEL.get(p, "unknown provider"), live=live(), test_enabled=bool(os.environ.get("ALERT_ADMIN_TOKEN")),
                repeat_hours=float(os.environ.get("ALERT_REPEAT_HOURS", "24")), cities=cs, recent=log)
