"""Government / utility reservoir-level feeds.
The departments that hold fully current readings release them about once a week, and the public cannot read their live systems.
So every poll cycle (default 20 min) the backend checks each configured feed (a CSV in data/govt_drop/ or a URL the department provides)
and ingests ONLY when the content has changed. Between releases the numbers stay as they are; when a new file appears it is picked up on the next cycle."""
import os, json, hashlib, pathlib, csv, io, datetime as dt, urllib.request
from .db import conn, LOCK

ROOT = pathlib.Path(__file__).parents[2]
CFG = json.loads((ROOT / "data" / "govt_sources.json").read_text())["cities"]
DATASET = "government reservoir feed"

def _drop(): return pathlib.Path(os.environ.get("AQUA_GOVT_DROP", ROOT / "data" / "govt_drop"))
def _now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def _init(): conn().execute("CREATE TABLE IF NOT EXISTS govt_feed(city_id TEXT PRIMARY KEY,last_checked TEXT,last_changed TEXT,content_hash TEXT,data_as_of TEXT,records INT,status TEXT,error TEXT)")

def _read(cid, feed):
    url = feed.get("url")
    if url:
        req = urllib.request.Request(url, headers={"User-Agent": "AQUAFORECAST"})
        tok = os.environ.get(feed.get("auth_env") or "", "")
        if tok: req.add_header("Authorization", tok)
        return urllib.request.urlopen(req, timeout=20).read().decode("utf-8-sig")
    f = _drop() / f"{cid}.csv"
    return f.read_text(encoding="utf-8-sig") if f.exists() else None

def _parse(cid, text, today):
    rows = list(csv.DictReader(io.StringIO(text))); good, errs = [], []
    if not rows or not {"reservoir", "date", "storage_pct"} <= set(rows[0]): raise ValueError("CSV needs header: reservoir,date,storage_pct")
    for i, r in enumerate(rows):
        try:
            c = (r.get("city") or cid).strip().lower()
            if c != cid: raise ValueError(f"row is for '{c}', expected '{cid}'")
            d = dt.date.fromisoformat(r["date"].strip()); p = float(r["storage_pct"])
            if d > today: raise ValueError("future date")
            if not 0 <= p <= 100: raise ValueError("storage_pct outside 0-100")
            good.append((cid, (r["reservoir"] or "ALL").strip(), d.isoformat(), p))
        except Exception as e: errs.append(f"row {i + 2}: {e}")
    return good, errs

def check_city(cid, today=None):
    today = today or dt.date.today(); cfg = CFG[cid]; ts = _now()
    with LOCK:
        _init(); db = conn(); prev = db.execute("SELECT * FROM govt_feed WHERE city_id=?", (cid,)).fetchone()
        def save(status, err=None, **kw):
            v = dict(last_changed=prev["last_changed"] if prev else None, content_hash=prev["content_hash"] if prev else None, data_as_of=prev["data_as_of"] if prev else None, records=prev["records"] if prev else 0); v.update(kw)
            db.execute("INSERT OR REPLACE INTO govt_feed VALUES(?,?,?,?,?,?,?,?)", (cid, ts, v["last_changed"], v["content_hash"], v["data_as_of"], v["records"], status, err)); db.commit(); return status
        def log(rec, ok_n, bad_n, ok, err): db.execute("INSERT INTO data_ingestion_logs(source,dataset,city_id,ts,records_received,records_valid,records_rejected,ok,error) VALUES(?,?,?,?,?,?,?,?,?)", (cfg["authority"], DATASET, cid, ts, rec, ok_n, bad_n, int(ok), err)); db.commit()
        try: text = _read(cid, cfg["feed"])
        except Exception as e:
            log(0, 0, 0, False, f"SOURCE CONNECTION FAILED: {e}"); return save("FAILED", f"SOURCE CONNECTION FAILED: {e}")
        if text is None: return save("WAITING" if (prev and prev["data_as_of"]) else "NOT CONFIGURED")
        h = hashlib.sha256(text.encode()).hexdigest()
        if prev and prev["content_hash"] == h: return save("UNCHANGED")
        try: good, errs = _parse(cid, text, today)
        except Exception as e:
            log(0, 0, 0, False, str(e)); return save("FAILED", str(e))
        if not good:
            log(len(errs), 0, len(errs), False, "; ".join(errs[:3])); return save("FAILED", "no valid rows: " + "; ".join(errs[:3]))
        for g in good: db.execute("INSERT OR REPLACE INTO reservoir_observations VALUES(?,?,?,?,?)", (*g, ts))
        log(len(good) + len(errs), len(good), len(errs), True, "; ".join(errs[:3]) or None)
        return save("UPDATED", "; ".join(errs[:3]) or None, last_changed=ts, content_hash=h, data_as_of=max(g[2] for g in good), records=len(good))

def check_all(cities=None):
    for cid in CFG:
        if cities is None or cid in cities:
            try: check_city(cid)
            except Exception: pass

def feed_status(cities, today=None):
    today = today or dt.date.today(); out = []
    with LOCK:
        _init(); db = conn()
        for cid, cfg in CFG.items():
            if cid not in cities: continue
            r = db.execute("SELECT * FROM govt_feed WHERE city_id=?", (cid,)).fetchone(); asof = r["data_as_of"] if r else None; lvl = None
            if asof:
                rows = db.execute("SELECT reservoir,storage_pct FROM reservoir_observations WHERE city_id=? AND date=?", (cid, asof)).fetchall()
                allr = [x for x in rows if x["reservoir"] == "ALL"]
                lvl = allr[0]["storage_pct"] if allr else (sum(x["storage_pct"] for x in rows) / len(rows) if rows else None)
            nxt = (dt.date.fromisoformat(asof) + dt.timedelta(days=cfg["cadence_days"])) if asof else None
            st = r["status"] if r else "NOT CHECKED YET"
            if st == "NOT CONFIGURED" or (not r and not cfg["feed"].get("url") and not (_drop() / f"{cid}.csv").exists()): shown = "NOT CONFIGURED"
            elif st == "FAILED": shown = "FAILED"
            elif not asof: shown = "WAITING FOR FIRST FEED"
            elif nxt and today > nxt + dt.timedelta(days=7): shown = "OVERDUE (no new release)"
            else: shown = "UPDATED THIS CYCLE" if st == "UPDATED" else "UP TO DATE (unchanged since last check)"
            out.append(dict(city=cid, name=cities[cid]["name"], authority=cfg["authority"], cadence_days=cfg["cadence_days"], feed_type="url" if cfg["feed"].get("url") else "drop_folder",
                            status=shown, last_checked=r["last_checked"] if r else None, last_changed=r["last_changed"] if r else None, data_as_of=asof,
                            next_expected=nxt.isoformat() if nxt else None, level_pct=lvl, error=r["error"] if r else None))
    return out
