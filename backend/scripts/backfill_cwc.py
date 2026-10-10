"""Backfill archived CWC weekly bulletins into the database so the ML layer has history to learn from.

  python scripts/backfill_cwc.py --pdf-dir ./bulletins          # every *.pdf in a folder
  python scripts/backfill_cwc.py --urls bulletin_urls.txt       # one direct PDF link per line (needs internet)

Run from backend/. Uses the same parser as the live watcher, so the same validation applies (date not in the future, storage 0-101%).
Each file is reported; failures are listed, never skipped silently."""
import sys, pathlib, argparse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from app import cwc

ap = argparse.ArgumentParser(); ap.add_argument("--pdf-dir"); ap.add_argument("--urls"); a = ap.parse_args()
items = []
if a.pdf_dir: items += [(p.name, p.read_bytes) for p in sorted(pathlib.Path(a.pdf_dir).glob("*.pdf"))]
if a.urls:
    for u in [x.strip() for x in pathlib.Path(a.urls).read_text().splitlines() if x.strip() and not x.startswith("#")]:
        items.append((u, (lambda u=u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 AQUAFORECAST"}), timeout=60).read())))
if not items: sys.exit("nothing to do: pass --pdf-dir and/or --urls")
ok = bad = 0
for name, get in items:
    try:
        d, n, rej = cwc.ingest_pdf(get()); ok += 1; print(f"OK    {name}: bulletin {d}, {n} reservoirs stored, {rej} rejected")
    except Exception as e:
        bad += 1; print(f"FAIL  {name}: {e}")
dates = {r["date"] for r in cwc.history_rows()}
print(f"\n{ok} stored, {bad} failed. Database now holds {len(dates)} bulletin dates ({min(dates) if dates else '-'} to {max(dates) if dates else '-'}). Need at least 52 for the backtest.")
