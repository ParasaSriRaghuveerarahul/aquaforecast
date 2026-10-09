# Model card: AQUAFORECAST learned early-warning model (v6)

**Purpose.** Give water-utility control rooms 1 to 4 weeks of warning that a reservoir is heading below its normal storage for the week, with an honest uncertainty band. Decision support, not an automatic trigger.

**Not for.** City demand forecasting, flood forecasting, or any decision without a human reading the explanation (the water-balance engine) alongside it.

**Data.** Central Water Commission weekly bulletin (178 reservoirs): storage % of capacity, normal %, last-year %, capacity. Stored by `app/cwc.py` (live) and `scripts/backfill_cwc.py` (archive). Fill in after the real run: `[N bulletin dates, first to last, N reservoirs]`.

**Model.** Quantile gradient boosting for q10/q50/q90 of the 1/2/4-week change in storage; split-conformal widening so the 80% band reaches its target coverage on held-out data. Features: see `ml.FEATURES`. Future normal is not yet published, so at forecast time the normal's seasonal change uses the same week one year earlier.

**Validation.** Rolling-origin backtest, training only on targets known at each fold start. Baselines: persistence, 4-week straight line, persistence + the normal's seasonal change. Reported: MAE/RMSE, skill with 95% bootstrap interval vs persistence and vs the strongest baseline, band coverage and width, alert precision/recall/false-alarm on all weeks and on onset events.

**Results (fill from `data/ml_report.json`, do not edit by hand).**
| Horizon | Model MAE | Strongest baseline MAE | Skill vs strongest baseline [95% CI] | 80% band coverage | Onset events (n) | Recall / precision |
|---|---|---|---|---|---|---|
| 1 wk | | | | | | |
| 2 wk | | | | | | |
| 4 wk | | | | | | |

**Known failure modes.** (1) Few monsoon cycles in the history means the seasonal pattern is learned from few examples. (2) Operating rules (releases, irrigation demand) are not observed, so sudden policy changes are not predicted. (3) Storage is reservoir-wide; a city's supply also depends on treatment, distribution and demand, which only the water-balance engine models. (4) A new bulletin layout can break the parser; the feed then shows FAILED, never silent.

**Monitoring.** Each new bulletin gives new ground truth; rerun `run_backtest.py` monthly and compare coverage and skill with the previous report.
