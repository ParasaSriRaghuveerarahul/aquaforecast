"""Red-alert SMS / WhatsApp notifications.
RED = the engine's CRITICAL level: projected supply-demand failure in under 14 days (same rule that colours the Alert Center red).
ONLY red sends. Watch / high-risk / normal never do. Safe by design:
  * one alert when a city ENTERS red, repeated at most every ALERT_REPEAT_HOURS (default 24) while it stays red;
  * recipients whose send failed are retried on the next poll cycles (max ALERT_MAX_RETRIES, default 6), then dropped until the next window;
  * every attempt is logged (numbers masked); provider errors are stored with phone numbers scrubbed;
  * ALERT_PROVIDER=log (default) is a dry run: nothing leaves the server until real provider keys are set;
  * the TEST endpoint needs ALERT_ADMIN_TOKEN and is limited to 5 sends per hour, so the public site cannot be used to spam the numbers.
Providers: twilio_sms | twilio_whatsapp | webhook (any HTTP service: MSG91 / Fast2SMS / n8n / Make) | log."""
import os, re, json, uuid, base64, datetime as dt, urllib.request, urllib.parse, urllib.error
from . import engine as E
from .db import conn, LOCK

RED = "CRITICAL"
LABEL = {"log": "dry-run log (no provider configured)", "twilio_sms": "Twilio SMS", "twilio_whatsapp": "Twilio WhatsApp", "webhook": "custom webhook"}

def _now(): return dt.datetime.now(dt.timezone.utc)
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
    raw = [x for x in re.split(r"[,;\s]+", os.environ.get("ALERT_PHONES", "")) if x]; good, bad = [], 0
    for x in raw:
        n = normalize(x)
        if n and n not in good: good.append(n)
        elif not n: bad += 1
    return good, bad
def mask(n): return n[:3] + " ******" + n[-4:]
def _scrub(t): return re.sub(r"\+?\d[\d\s-]{7,}\d", "[number]", str(t))[:160]

def live():
    p = os.environ.get("ALERT_PROVIDER", "log"); g = os.environ.get
    if p in ("twilio_sms", "twilio_whatsapp"): return bool(g("TWILIO_ACCOUNT_SID") and g("TWILIO_AUTH_TOKEN") and (g("TWILIO_FROM") or g("TWILIO_MESSAGING_SERVICE_SID")))
    if p == "webhook": return bool(g("ALERT_WEBHOOK_URL"))
    return False

def send_one(to, text):
    """Returns (ok, detail). Never raises."""
    p = os.environ.get("ALERT_PROVIDER", "log"); g = os.environ.get
    if p == "log": return True, "dry-run: ALERT_PROVIDER=log, nothing was sent"
    if not live(): return False, f"provider '{p}' is missing its keys/URL"
    try:
        if p in ("twilio_sms", "twilio_whatsapp"):
            sid, tok, wa = g("TWILIO_ACCOUNT_SID"), g("TWILIO_AUTH_TOKEN"), p == "twilio_whatsapp"
            data = {"To": ("whatsapp:" if wa else "") + to, "Body": text}
            if wa: f = g("TWILIO_FROM", ""); data["From"] = f if f.startswith("whatsapp:") else "whatsapp:" + f
            elif g("TWILIO_MESSAGING_SERVICE_SID"): data["MessagingServiceSid"] = g("TWILIO_MESSAGING_SERVICE_SID")
            else: data["From"] = g("TWILIO_FROM")
            req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=urllib.parse.urlencode(data).encode(),
                                         headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()})
            return True, "queued " + json.load(urllib.request.urlopen(req, timeout=15)).get("sid", "")[:12]
        if p == "webhook":
            h = {"Content-Type": "application/json"}
            if g("ALERT_WEBHOOK_TOKEN"): h["Authorization"] = g("ALERT_WEBHOOK_TOKEN")
            urllib.request.urlopen(urllib.request.Request(g("ALERT_WEBHOOK_URL"), json.dumps({"to": to, "message": text, "source": "aquaforecast"}).encode(), h), timeout=15)
            return True, "webhook accepted"
        return False, f"unknown ALERT_PROVIDER '{p}'"
    except urllib.error.HTTPError as e:
        try: m = json.loads(e.read().decode()).get("message", "")
        except Exception: m = ""
        return False, _scrub(f"HTTP {e.code} {m}")
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
    return dict(sent=len(out) - len(fails), failed=len(fails), provider=LABEL.get(os.environ.get("ALERT_PROVIDER", "log"), "unknown"), live=live(), results=out)

def status_info(cities):
    to, bad = recipients(); p = os.environ.get("ALERT_PROVIDER", "log")
    with LOCK:
        _init(); db = conn(); st = {r["city_id"]: r for r in db.execute("SELECT * FROM alert_state")}
        log = [dict(ts=r["ts"], city=r["city_id"], kind=r["kind"], to=r["recipient"], ok=bool(r["ok"]), detail=r["detail"]) for r in db.execute("SELECT * FROM alert_log ORDER BY id DESC LIMIT 12")]
        cs = []
        for cid, c in cities.items():
            s = city_state(cid, c); cs.append(dict(id=cid, city=s["city"], status=s["status"], horizon_days=s["day"], red=s["status"] == RED, last_alert=st[cid]["last_sent"] if cid in st else None))
    return dict(red_only=True, rule="CRITICAL = projected supply-demand failure in under 14 days", recipients=[mask(n) for n in to], invalid_numbers=bad,
                provider=p, provider_label=LABEL.get(p, "unknown provider"), live=live(), test_enabled=bool(os.environ.get("ALERT_ADMIN_TOKEN")),
                repeat_hours=float(os.environ.get("ALERT_REPEAT_HOURS", "24")), cities=cs, recent=log)
