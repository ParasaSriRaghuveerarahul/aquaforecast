"""Water-balance engine, scenarios, optimizer, attribution, Monte Carlo. Pure functions, no I/O."""
import numpy as np
TM = 120
LV0 = dict(ind=100, rec=0, cap=0, con=0, rel=0, ext=0)
SCEN = {"now": ("Latest reported level", dict(rain=0, dem=0, fail=0, gr=.05), -1),
        "normal": ("Normal rainfall", dict(rain=0, dem=-.08, fail=0, gr=.05), 1),
        "heavy": ("Extreme rainfall", dict(rain=.2, dem=-.05, fail=0, gr=.1), 1),
        "drought": ("Drought", dict(rain=-.5, dem=.05, fail=0, gr=.12), .15),
        "spike": ("Demand spike", dict(rain=-.1, dem=.2, fail=0, gr=.12), .45),
        "infra": ("Inflow / infrastructure reduction", dict(rain=-.25, dem=0, fail=.15, gr=.12), .45),
        "crisis": ("Water crisis (stress level)", dict(rain=-.25, dem=0, fail=0, gr=.12), 0)}
LC = {"ind": dict(st=-5, min=60, c=1.2), "rec": dict(st=2, max=30, c=1), "cap": dict(st=3, max=40, c=.7),
      "con": dict(st=2, max=30, c=1.5), "rel": dict(st=1, max=10, c=1.4), "ext": dict(st=1, max=1, c=2)}

def params(c, key):
    _, p, w = SCEN[key]
    rC = c.get("rC", round(c["fl"] + 30 * (c["D"] - c["S"]) * 1.3 / c["C"], 3))
    return {**p, "ev": c.get("ev", 0), "r0": c["snap"] if w < 0 else rC + w * (c["rN"] - rC), **LV0}

def simulate(c, p):
    C, D0, S0, FL = c["C"], c["D"], c["S"], c["fl"]
    R = p["r0"] * C; x = -(p["rain"] + .25)
    dec = max(.05, .8 * (1 + 2 * x)) * D0 / 842
    sb = S0 * (1 + .3 * (p["rain"] + .25)) * (1 - p["fail"])
    d, s, r, day = [], [], [], None
    for t in range(TM + 1):
        dem = D0 * (1 + p["dem"]) * (1 + p["gr"] * t / 60) * (1 - .2 * (1 - p["ind"] / 100)) * (1 - p["con"] / 100 * .65)
        sup = (max(0, sb - dec * t) + p["rec"] * D0 * .003 + p["cap"] * D0 * .00107 * max(.3, 1 + p["rain"])
               + p["rel"] * D0 * .0043 + p["ext"] * D0 * .0356)
        d.append(dem); s.append(sup)
        R = min(C, R + sup - dem - p.get("ev", 0) * D0); r.append(R / C * 100)
        if day is None and R <= FL * C: day = t
    return dict(demand=d, supply=s, reserve_pct=r, day=day)

def horizon(c, p):
    d = simulate(c, p)["day"]; return TM + 1 if d is None else d

def status(day):
    return "NORMAL" if day is None or day >= 60 else "WATCH" if day >= 30 else "HIGH RISK" if day >= 14 else "CRITICAL"

def attribution(c, p):
    b = horizon(c, p); out = []
    for n, k in [("Rainfall deficit", {"rain": 0}), ("Demand growth", {"gr": 0}),
                 ("Demand level shift", {"dem": 0}), ("Infrastructure failure", {"fail": 0})]:
        g = max(0, horizon(c, {**p, **k}) - b)
        if g: out.append((n, g))
    tot = sum(g for _, g in out) or 1
    return sorted([dict(driver=n, share_pct=round(g / tot * 100, 1), days_gained_if_removed=g) for n, g in out], key=lambda a: -a["share_pct"])

def optimize(c, p, target=60):
    q = dict(p); score = lambda x: sum(simulate(c, x)["reserve_pct"])
    for _ in range(120):
        if horizon(c, q) >= target: break
        best, bs = None, 0
        for k, l in LC.items():
            v = q[k] + l["st"]
            if ("max" in l and v > l["max"]) or ("min" in l and v < l["min"]): continue
            n = {**q, k: v}; g = (score(n) - score(q)) / (abs(l["st"]) * l["c"])
            if g > bs: bs, best = g, n
        if not best: break
        q = best
    cost = sum(abs(q[k] - p[k]) / abs(l["st"]) * l["c"] for k, l in LC.items())
    return dict(plan=q, horizon_before=horizon(c, p), horizon_after=horizon(c, q), cost_index=round(cost, 1),
                changes={k: q[k] - p[k] for k in LC if q[k] != p[k]})

def monte_carlo(c, p, n=200, seed=11):
    rng = np.random.default_rng(seed); ds = []
    for _ in range(n):
        q = {**p, "rain": p["rain"] + rng.normal(0, .12), "dem": p["dem"] + rng.normal(0, .06),
             "gr": max(0, p["gr"] + rng.normal(0, .03)), "fail": min(.5, max(0, p["fail"] + abs(rng.normal(0, .02))))}
        ds.append(horizon(c, q))
    a = np.array(ds)
    return dict(runs=n, p_shortage_30d=float((a <= 30).mean()), p_shortage_60d=float((a <= 60).mean()),
                horizon_p10=int(np.percentile(a, 10)), horizon_p50=int(np.percentile(a, 50)), horizon_p90=int(np.percentile(a, 90)))
