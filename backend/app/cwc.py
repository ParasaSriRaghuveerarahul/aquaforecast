"""CWC weekly reservoir bulletin (178 reservoirs) watcher.
Every poll cycle (but at most every CWC_CHECK_HOURS, default 6) the backend downloads the bulletin PDF from CWC_BULLETIN_URL
(or data/cwc_source.json "url"), and ONLY when the file changed parses the 'Weekly report of 178 important reservoirs' table and stores it.
Failures are logged and shown (never hidden). Google Drive share links are converted to direct downloads."""
import os, re, io, json, hashlib, pathlib, datetime as dt, urllib.request
from .db import conn, LOCK

ROOT = pathlib.Path(__file__).parents[2]
DATASET = "CWC weekly reservoir bulletin"
SOURCE = "Central Water Commission (weekly reservoir storage bulletin)"
ROW = re.compile(r"(\d{1,3}) ([A-Z][A-Z .&'()/-]*?) ([A-Z][a-z]+(?: [A-Z][a-z]+)?) ((?:-?\d+\.\d+ ){4})(\d{2}\.\d{2}\.\d{4}) ((?:-?\d+\.\d+ ?){10})")
BLR = ("KRISHNARAJA SAGARA", "KABINI")   # Bengaluru: Cauvery allocation proxy

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def _init():
    conn().executescript("""CREATE TABLE IF NOT EXISTS cwc_reservoirs(date TEXT,reservoir TEXT,state TEXT,cap_bcm REAL,stor_bcm REAL,pct REAL,last_year_pct REAL,normal_pct REAL,fetched_at TEXT,PRIMARY KEY(date,reservoir));
    CREATE TABLE IF NOT EXISTS cwc_feed(id INTEGER PRIMARY KEY CHECK(id=1),last_checked TEXT,last_changed TEXT,content_hash TEXT,bulletin_date TEXT,records INT,status TEXT,error TEXT);""")

def url():
    u = (os.environ.get("CWC_BULLETIN_URL") or "").strip()
    if not u:
        try: u = (json.loads((ROOT / "data" / "cwc_source.json").read_text()).get("url") or "").strip()
        except Exception: u = ""
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", u)
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}" if m else u

def _fetch(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 AQUAFORECAST"})
    return urllib.request.urlopen(req, timeout=60).read()

def _pdf_text(b):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(b)).pages)

def parse(text, today=None):
    today = today or dt.date.today(); t = re.sub(r"\s+", " ", text) + " "; rows, errs = [], []
    for m in ROW.finditer(t):
        try:
            n = [float(x) for x in m.group(6).split()]; d = dt.datetime.strptime(m.group(5), "%d.%m.%Y").date()
            cap, stor, pct, lypct, normpct = float(m.group(4).split()[3]), n[1], n[2], n[5], n[7]
            if d > today: raise ValueError("future date")
            if not 0 <= pct <= 101: raise ValueError("storage_pct outside range")
            rows.append(dict(reservoir=m.group(2).strip(), state=m.group(3), date=d.isoformat(), cap=cap, stor=stor, pct=pct, ly=lypct, normal=normpct))
        except Exception as e: errs.append(f"{m.group(2)}: {e}")
    return rows, errs

def check(cities=None, force=False):
    """Returns the feed status string. Safe to call every poll cycle."""
    ts = _now(); hours = float(os.environ.get("CWC_CHECK_HOURS") or 6)
    with LOCK:
        _init(); db = conn(); prev = db.execute("SELECT * FROM cwc_feed WHERE id=1").fetchone()
        if prev and prev["last_checked"] and not force and prev["status"] in ("UPDATED", "UNCHANGED"):
            if (dt.datetime.fromisoformat(ts) - dt.datetime.fromisoformat(prev["last_checked"])).total_seconds() < hours * 3600: return prev["status"]
        def save(status, err=None, **kw):
            v = dict(last_changed=prev["last_changed"] if prev else None, content_hash=prev["content_hash"] if prev else None, bulletin_date=prev["bulletin_date"] if prev else None, records=prev["records"] if prev else 0); v.update(kw)
            db.execute("INSERT OR REPLACE INTO cwc_feed VALUES(1,?,?,?,?,?,?,?)", (ts, v["last_changed"], v["content_hash"], v["bulletin_date"], v["records"], status, err)); db.commit(); return status
        def log(rec, ok_n, bad_n, ok, err): db.execute("INSERT INTO data_ingestion_logs(source,dataset,city_id,ts,records_received,records_valid,records_rejected,ok,error) VALUES(?,?,?,?,?,?,?,?,?)", (SOURCE, DATASET, "india", ts, rec, ok_n, bad_n, int(ok), err)); db.commit()
        u = url()
        if not u: log(0, 0, 0, False, "NOT CONFIGURED: set CWC_BULLETIN_URL or data/cwc_source.json"); return save("NOT CONFIGURED", "set CWC_BULLETIN_URL or data/cwc_source.json")
        try:
            b = _fetch(u)
            if not b[:5].startswith(b"%PDF"): raise ValueError("download is not a PDF (the link may need sharing set to 'Anyone with the link', or the site blocked the request)")
        except Exception as e:
            log(0, 0, 0, False, f"SOURCE CONNECTION FAILED: {e}"); return save("FAILED", f"SOURCE CONNECTION FAILED: {e}")
        h = hashlib.sha256(b).hexdigest()
        if prev and prev["content_hash"] == h: log(0, 0, 0, True, None); return save("UNCHANGED")
        try:
            rows, errs = parse(_pdf_text(b))
            if len(rows) < 100: raise ValueError(f"only {len(rows)} reservoir rows could be read; the bulletin layout may have changed")
        except Exception as e:
            log(0, 0, 0, False, str(e)); return save("FAILED", str(e))
        for r in rows: db.execute("INSERT OR REPLACE INTO cwc_reservoirs VALUES(?,?,?,?,?,?,?,?,?)", (r["date"], r["reservoir"], r["state"], r["cap"], r["stor"], r["pct"], r["ly"], r["normal"], ts))
        log(len(rows) + len(errs), len(rows), len(errs), True, "; ".join(errs[:3]) or None)
        return save("UPDATED", "; ".join(errs[:3]) or None, last_changed=ts, content_hash=h, bulletin_date=max(r["date"] for r in rows), records=len(rows))

def status():
    with LOCK:
        _init(); db = conn(); r = db.execute("SELECT * FROM cwc_feed WHERE id=1").fetchone()
        if not r or not r["bulletin_date"]: return dict(status=(r["status"] if r else "NOT CHECKED YET"), configured=bool(url()), bulletin_date=None, last_checked=(r["last_checked"] if r else None), error=(r["error"] if r else None), levels={}, bengaluru_pct=None)
        rows = db.execute("SELECT reservoir,state,cap_bcm,stor_bcm,pct,last_year_pct,normal_pct FROM cwc_reservoirs WHERE date=?", (r["bulletin_date"],)).fetchall()
        lv = {x["reservoir"]: x["pct"] for x in rows}; b = [x for x in rows if x["reservoir"] in BLR]
        blr = round(sum(x["stor_bcm"] for x in b) / sum(x["cap_bcm"] for x in b) * 100, 2) if len(b) == len(BLR) else None
        return dict(status=r["status"], configured=True, bulletin_date=r["bulletin_date"], last_checked=r["last_checked"], last_changed=r["last_changed"], records=r["records"], error=r["error"], levels=lv, bengaluru_pct=blr, reservoirs=[[x["reservoir"], x["state"], x["pct"], x["last_year_pct"], x["normal_pct"]] for x in rows])

def ingest_pdf(b, today=None):
    """Parse one bulletin PDF (bytes) and store its rows WITHOUT touching the live-feed status. Used to backfill archived weekly bulletins.
    Returns (bulletin_date, rows_stored, rows_rejected). Raises ValueError if it does not look like the 178-reservoir bulletin."""
    if not b[:5].startswith(b"%PDF"): raise ValueError("not a PDF")
    rows, errs = parse(_pdf_text(b), today)
    if len(rows) < 100: raise ValueError(f"only {len(rows)} reservoir rows could be read; not the 178-reservoir bulletin or layout changed")
    ts = _now()
    with LOCK:
        _init(); db = conn()
        for r in rows: db.execute("INSERT OR REPLACE INTO cwc_reservoirs VALUES(?,?,?,?,?,?,?,?,?)", (r["date"], r["reservoir"], r["state"], r["cap"], r["stor"], r["pct"], r["ly"], r["normal"], ts))
        db.commit()
    return max(r["date"] for r in rows), len(rows), len(errs)

def history_rows():
    """All stored bulletin rows in the shape app.ml expects."""
    with LOCK:
        _init(); return [dict(reservoir=x["reservoir"], date=x["date"], pct=x["pct"], normal=x["normal_pct"], ly=x["last_year_pct"], cap=x["cap_bcm"])
                         for x in conn().execute("SELECT reservoir,date,pct,normal_pct,last_year_pct,cap_bcm FROM cwc_reservoirs ORDER BY date").fetchall()]
