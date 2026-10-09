"""Train the learned early-warning model and run the rolling-origin backtest on the stored CWC history.

  python scripts/run_backtest.py              # real stored history -> data/ml_report.json (served by /api/ml/validation)
  python scripts/run_backtest.py --synthetic  # pipeline rehearsal on SYNTHETIC data -> data/ml_report_SYNTHETIC.json (never served, never presentable as results)
Run from backend/."""
import sys, pathlib, argparse, json
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from app import ml, cwc

ap = argparse.ArgumentParser(); ap.add_argument("--synthetic", action="store_true"); a = ap.parse_args()
if a.synthetic:
    print("*** SYNTHETIC DATA: rehearsal only. These numbers say nothing about real reservoirs. ***")
    rep = ml.backtest(ml.synthetic_rows(), source="SYNTHETIC"); out = ml.write_report(rep, ml.ROOT / "data" / "ml_report_SYNTHETIC.json")
else:
    rep = ml.backtest(cwc.history_rows()); out = ml.write_report(rep) if rep["status"] == "OK" else None
print(json.dumps({k: rep[k] for k in ("status", "data_source", "data")}, indent=1))
if rep["status"] != "OK": sys.exit(rep.get("message"))
for h, o in rep["horizons"].items():
    if o.get("status") != "OK": print(f"{h}w: {o['status']}"); continue
    m = o["methods"]; vb = m["model"]["vs_best_baseline"]
    print(f"{h}w  MAE model {m['model']['mae']} | persistence {m['persistence']['mae']} | trend {m['linear_trend']['mae']} | climatology {m['climatology_delta']['mae']}"
          f"  | skill vs persistence {m['model']['skill_vs_persistence']} {m['model']['skill_ci95']} | vs best baseline ({vb['baseline']}) {vb['skill']} {vb['ci95']}"
          f"  | 80% band coverage {o['interval']['coverage']}")
for l in rep["limits"]: print("LIMIT:", l)
print("report written to", out)
