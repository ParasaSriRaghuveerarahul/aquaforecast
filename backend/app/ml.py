"""Learned early-warning layer (v6).

Forecasts weekly reservoir storage 1, 2 and 4 weeks ahead with an 80% uncertainty band, and is VALIDATED by a rolling-origin
backtest against three naive baselines. The water-balance engine (engine.py) stays the explainable what-if layer; this layer
supplies measured forecast skill.

Honesty rules built in:
  * No report is produced with fewer than MIN_WEEKS bulletin dates (status INSUFFICIENT HISTORY).
  * Training rows for a fold only use targets already known at the fold cutoff (no look-ahead; unit-tested).
  * Skill vs persistence carries a bootstrap 95% interval (resampled by bulletin date); alert metrics show event counts.
  * The 80% band is conformally calibrated, and its empirical coverage on unseen weeks is reported, not assumed.
  * Synthetic data is tagged source=SYNTHETIC and is never written to the file the API serves.
"""
import json, math, pathlib, datetime as dt
import numpy as np

HORIZONS = (1, 2, 4)          # weeks ahead
QUANT = (0.1, 0.5, 0.9)
NOMINAL = 0.8                 # nominal coverage of the (q10, q90) band
MIN_WEEKS = 52                # least history we will report on
MIN_TRAIN = 300               # least training rows for a fold
ALERT_RATIO = 0.8             # alert event: storage below 80% of the normal for that week (bulletin's "close to normal" edge)
FEATURES = ["storage_pct", "normal_pct", "gap_to_normal", "ratio_to_normal", "gap_to_last_year", "chg_1w", "chg_2w", "chg_4w", "week_sin", "week_cos", "log_capacity", "normal_change_ahead"]
ROOT = pathlib.Path(__file__).parents[2]
REPORT_PATH = ROOT / "data" / "ml_report.json"


# ---------- data ----------
def panel(rows):
    """rows: dicts with reservoir,date(iso),pct,normal,ly,cap -> {reservoir: {date: row}} keeping only physically valid rows."""
    P = {}
    for r in rows:
        try:
            if r["normal"] and r["normal"] > 0 and 0 <= r["pct"] <= 101:
                P.setdefault(r["reservoir"], {})[dt.date.fromisoformat(r["date"])] = r
        except Exception:
            continue
    return P


def _near(dm, d):
    for o in (0, -1, 1):          # bulletins are weekly; tolerate a one-day shift
        r = dm.get(d + dt.timedelta(days=o))
        if r:
            return r
    return None


def _feat(dm, d, dn=0.0):
    r = dm[d]; l = [_near(dm, d - dt.timedelta(weeks=k)) for k in (1, 2, 4)]
    if None in l:
        return None
    w = d.isocalendar()[1] / 52.0 * 2 * math.pi
    x = np.array([r["pct"], r["normal"], r["pct"] - r["normal"], r["pct"] / r["normal"], r["pct"] - (r.get("ly") or 0.0),
                  r["pct"] - l[0]["pct"], r["pct"] - l[1]["pct"], r["pct"] - l[2]["pct"], math.sin(w), math.cos(w), math.log(max(r.get("cap") or 0.0, 1e-3)), dn])
    return x, r["pct"] - l[2]["pct"]


def samples(P, h):
    out = []
    for res, dm in P.items():
        for d, r in dm.items():
            t = _near(dm, d + dt.timedelta(weeks=h))
            if t is None:
                continue
            f = _feat(dm, d, t["normal"] - r["normal"])   # the normal is a fixed climatology, so its seasonal change ahead is known in advance
            if f is None:
                continue
            x, d4 = f
            out.append(dict(res=res, d=d, td=dt.date.fromisoformat(t["date"]), x=x, y=t["pct"] - r["pct"], p0=r["pct"], n0=r["normal"], nt=t["normal"], pt=t["pct"], d4=d4))
    return sorted(out, key=lambda s: (s["d"], s["res"]))


def fold_split(S, block):
    """Train on rows whose TARGET was already known at the block's first date; test on rows originating inside the block."""
    T = min(block); b = set(block)
    return [s for s in S if s["td"] <= T and s["d"] < T], [s for s in S if s["d"] in b]


# ---------- baselines ----------
def _clip(a): return np.clip(a, 0, 100)
def baselines(S, h):
    p0 = np.array([s["p0"] for s in S]); d4 = np.array([s["d4"] for s in S]); n0 = np.array([s["n0"] for s in S]); nt = np.array([s["nt"] for s in S])
    return {"persistence": _clip(p0), "linear_trend": _clip(p0 + h * d4 / 4.0), "climatology_delta": _clip(p0 + nt - n0)}


# ---------- model ----------
def _gbm(q, seed):
    from sklearn.ensemble import GradientBoostingRegressor
    return GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=120, max_depth=3, learning_rate=0.06, subsample=0.8, min_samples_leaf=20, random_state=seed)


def train(tr, seed=7):
    """Quantile gradient boosting on the weekly CHANGE in storage + split-conformal widening of the band (CQR)."""
    ds = sorted({s["d"] for s in tr})
    if len(ds) < 8:
        raise ValueError("too few training dates")
    cut = ds[int(len(ds) * 0.8)]
    fit = [s for s in tr if s["d"] < cut]; cal = [s for s in tr if s["d"] >= cut]
    if len(fit) < MIN_TRAIN * 0.5:
        raise ValueError("too few training rows")
    X = np.array([s["x"] for s in fit]); y = np.array([s["y"] for s in fit])
    models = {q: _gbm(q, seed).fit(X, y) for q in QUANT}
    qhat = 0.0
    if len(cal) >= 30:
        lo, _, hi = _raw(models, np.array([s["x"] for s in cal])); yc = np.array([s["y"] for s in cal])
        sc = np.maximum(lo - yc, yc - hi); n = len(sc)
        qhat = float(np.quantile(sc, min(1.0, math.ceil((n + 1) * NOMINAL) / n)))
    return dict(models=models, qhat=qhat, n_fit=len(fit), n_cal=len(cal))


def _raw(models, X):
    a = np.sort(np.vstack([models[q].predict(X) for q in QUANT]), axis=0)
    return a[0], a[1], a[2]


def predict(M, S):
    X = np.array([s["x"] for s in S]); lo, md, hi = _raw(M["models"], X); p0 = np.array([s["p0"] for s in S])
    return dict(lo=_clip(p0 + lo - M["qhat"]), md=_clip(p0 + md), hi=_clip(p0 + hi + M["qhat"]), lo_raw=_clip(p0 + lo), hi_raw=_clip(p0 + hi))


# ---------- metrics ----------
def _prf(actual, pred):
    a = np.asarray(actual, bool); p = np.asarray(pred, bool); tp = int((a & p).sum()); fp = int((~a & p).sum()); fn = int((a & ~p).sum()); tn = int((~a & ~p).sum())
    pr = tp / (tp + fp) if tp + fp else None; rc = tp / (tp + fn) if tp + fn else None
    return dict(precision=None if pr is None else round(pr, 3), recall=None if rc is None else round(rc, 3),
                false_alarm_rate=round(fp / (fp + tn), 3) if fp + tn else None, tp=tp, fp=fp, fn=fn, tn=tn)


def _skill_ci(err_m, err_b, dates, n=300, seed=3):
    """Skill = 1 - MAE_model / MAE_baseline, bootstrap-resampled by origin date (weeks, not rows, are the independent unit)."""
    rng = np.random.default_rng(seed); u = sorted(set(dates)); idx = {d: np.where(np.array(dates) == d)[0] for d in u}; out = []
    for _ in range(n):
        pick = np.concatenate([idx[u[i]] for i in rng.integers(0, len(u), len(u))])
        mb = err_b[pick].mean(); out.append(1 - err_m[pick].mean() / mb if mb > 0 else 0.0)
    return [round(float(np.percentile(out, 2.5)), 3), round(float(np.percentile(out, 97.5)), 3)]


def evaluate(T, preds, h):
    """T: test samples; preds: dict of method -> predicted storage pct (and 'model' band)."""
    y = np.array([s["pt"] for s in T]); dates = [s["d"] for s in T]; nt = np.array([s["nt"] for s in T]); n0 = np.array([s["n0"] for s in T]); p0 = np.array([s["p0"] for s in T])
    errs = {k: np.abs(v - y) for k, v in preds["point"].items()}; base = errs["persistence"]; methods = {}
    for k, v in preds["point"].items():
        methods[k] = dict(mae=round(float(errs[k].mean()), 3), rmse=round(float(np.sqrt(((v - y) ** 2).mean())), 3))
        if k != "persistence":
            methods[k]["skill_vs_persistence"] = round(float(1 - errs[k].mean() / base.mean()), 3) if base.mean() > 0 else None
            methods[k]["skill_ci95"] = _skill_ci(errs[k], base, dates)
    bl = {k: v["mae"] for k, v in methods.items() if k not in ("model",)}; best = min((k for k in bl if k != "persistence"), key=lambda k: bl[k])
    methods["model"]["vs_best_baseline"] = dict(baseline=best, skill=round(float(1 - errs["model"].mean() / errs[best].mean()), 3), ci95=_skill_ci(errs["model"], errs[best], dates))
    b = preds["band"]; cov = float(((y >= b["lo"]) & (y <= b["hi"])).mean()); cov_raw = float(((y >= b["lo_raw"]) & (y <= b["hi_raw"])).mean())
    interval = dict(nominal=NOMINAL, coverage=round(cov, 3), coverage_uncalibrated=round(cov_raw, 3), mean_width_pts=round(float((b["hi"] - b["lo"]).mean()), 2))
    actual = (y / nt) < ALERT_RATIO; onset = (p0 / n0) >= ALERT_RATIO
    alert = {k: (v / nt) < ALERT_RATIO for k, v in preds["point"].items()}
    alert["model_median"] = (preds["band"]["md"] / nt) < ALERT_RATIO; alert["model_sensitive"] = (b["lo"] / nt) < ALERT_RATIO
    ev = {}
    for nm, mask in (("onset_only", onset), ("all_weeks", np.ones(len(y), bool))):
        ev[nm] = dict(n=int(mask.sum()), n_events=int(actual[mask].sum()), enough_events=bool(actual[mask].sum() >= 10), methods={k: _prf(actual[mask], a[mask]) for k, a in alert.items()})
    return dict(n_test=len(T), methods=methods, interval=interval, events=ev)


# ---------- orchestration ----------
def backtest(rows, n_folds=4, train_frac=0.5, source="CWC weekly bulletins (stored)"):
    P = panel(rows); dates = sorted({d for dm in P.values() for d in dm})
    rep = dict(status="OK", data_source=source, generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               data=dict(bulletin_dates=len(dates), reservoirs=len(P), first=dates[0].isoformat() if dates else None, last=dates[-1].isoformat() if dates else None),
               method=dict(model="Quantile gradient boosting on weekly storage change (q10/q50/q90) + conformal band widening", features=FEATURES, horizons_weeks=list(HORIZONS),
                           validation=f"rolling-origin, {n_folds} expanding-window folds over the last {int((1 - train_frac) * 100)}% of dates; training uses only targets known at the fold start",
                           alert_event=f"storage below {int(ALERT_RATIO * 100)}% of the normal for that week",
                           baselines=["persistence (level stays flat)", "linear_trend (last 4 weeks extrapolated)", "climatology_delta (flat + normal's seasonal change)"]),
               horizons={}, feature_importance={}, latest_forecasts={}, limits=[])
    if len(dates) < MIN_WEEKS:
        rep.update(status="INSUFFICIENT HISTORY", need_bulletin_dates=MIN_WEEKS, message=f"{len(dates)} bulletin dates stored; at least {MIN_WEEKS} are needed before any accuracy claim. Run scripts/backfill_cwc.py on archived bulletins.")
        return rep
    origins = dates[int(len(dates) * train_frac):]; blocks = [list(b) for b in np.array_split(np.array(origins, dtype=object), n_folds) if len(b)]
    for h in HORIZONS:
        S = samples(P, h); T_all, pt, band, folds_used = [], {k: [] for k in ("persistence", "linear_trend", "climatology_delta", "model")}, {k: [] for k in ("lo", "md", "hi", "lo_raw", "hi_raw")}, 0
        for blk in blocks:
            tr, te = fold_split(S, blk)
            if len(tr) < MIN_TRAIN or not te:
                continue
            try: M = train(tr)
            except ValueError: continue
            folds_used += 1; pr = predict(M, te); bl = baselines(te, h); T_all += te
            for k in bl: pt[k].append(bl[k])
            pt["model"].append(pr["md"])
            for k in band: band[k].append(pr[k])
        if not T_all:
            rep["horizons"][str(h)] = dict(status="NOT ENOUGH DATA FOR A FOLD"); continue
        out = evaluate(T_all, dict(point={k: np.concatenate(v) for k, v in pt.items()}, band={k: np.concatenate(v) for k, v in band.items()}), h)
        out.update(folds=folds_used, status="OK"); rep["horizons"][str(h)] = out
        try:
            M = train(S); imp = sorted(zip(FEATURES, M["models"][0.5].feature_importances_), key=lambda a: -a[1])[:5]
            rep["feature_importance"][str(h)] = [dict(feature=f, importance=round(float(v), 3)) for f, v in imp]
            rep["latest_forecasts"] = _latest(P, rep["latest_forecasts"], h, M)
        except ValueError: pass
    rep["limits"] = _limits(rep)
    return rep


def _latest(P, acc, h, M):
    last = max(max(dm) for dm in P.values())
    for res, dm in P.items():
        d = max(dm)
        if (last - d).days > 7: continue
        r = dm[d]; ly = _near(dm, d + dt.timedelta(weeks=h - 52))   # future normal is not published yet: use the same week one year earlier
        f = _feat(dm, d, (ly["normal"] - r["normal"]) if ly else 0.0)
        if f is None: continue
        x, d4 = f; s = dict(x=x, p0=r["pct"]); pr = predict(M, [s]); e = acc.setdefault(res, dict(as_of=d.isoformat(), storage_pct=r["pct"], normal_pct=r["normal"], weeks={}))
        e["weeks"][str(h)] = dict(p10=round(float(pr["lo"][0]), 1), p50=round(float(pr["md"][0]), 1), p90=round(float(pr["hi"][0]), 1))
    return acc


def _limits(rep):
    L = ["Backtest covers only the stored bulletin dates; seasonality is learned from as many monsoon cycles as are stored.", "Storage is reservoir-wide; city demand and supply are not part of this model (they stay in the water-balance engine)."]
    for h, o in rep["horizons"].items():
        if o.get("status") == "OK":
            m = o["methods"]["model"]
            vb = m.get("vs_best_baseline")
            if m.get("skill_ci95") and m["skill_ci95"][0] <= 0: L.append(f"{h}-week horizon: skill vs persistence is not distinguishable from zero (95% interval includes 0).")
            if vb and vb["ci95"][0] <= 0: L.append(f"{h}-week horizon: the model is not clearly better than the strongest baseline ({vb['baseline']}); do not claim extra skill there.")
            if not o["events"]["onset_only"]["enough_events"]: L.append(f"{h}-week horizon: fewer than 10 onset events, so alert precision/recall are indicative only.")
    return L


def write_report(rep, path=REPORT_PATH):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(rep, indent=1))
    return path


def read_report():
    try: return json.loads(REPORT_PATH.read_text())
    except Exception: return dict(status="NOT RUN", message="No ML report yet. Backfill CWC bulletins (scripts/backfill_cwc.py), then run scripts/run_backtest.py.")


# ---------- synthetic data (tests and pipeline rehearsal ONLY; never real, never served by the API) ----------
def synthetic_rows(n_res=40, weeks=130, seed=5, start=dt.date(2024, 1, 4)):
    rng = np.random.default_rng(seed); rows = []; yr_shock = rng.normal(0, 0.15, weeks // 52 + 2)
    for i in range(n_res):
        amp, ph, base, cap = rng.uniform(15, 35), rng.uniform(-6, 6), rng.uniform(40, 55), rng.uniform(0.2, 5)
        a = 0.0
        for w in range(weeks):
            d = start + dt.timedelta(weeks=w); wk = d.isocalendar()[1]
            normal = base + amp * math.sin(2 * math.pi * (wk + ph - 14) / 52)
            a = 0.92 * a + rng.normal(0, 0.03) + (0.02 * yr_shock[w // 52] if wk == 26 else 0.0)
            pct = float(np.clip(normal * (1 + a + yr_shock[w // 52] * 0.3), 0, 100))
            rows.append(dict(reservoir=f"SYN {i:02d}", date=d.isoformat(), pct=round(pct, 2), normal=round(max(normal, 1.0), 2), ly=round(pct * rng.uniform(0.8, 1.2), 2), cap=cap))
    return rows
