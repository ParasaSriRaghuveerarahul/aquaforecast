# AQUAFORECAST: 3-minute pitch + judge Q&A
**0:00 Hook.** "Cities don't run out of water overnight. The warning signs appear weeks earlier. We find them, explain them, and test what to do."
**0:20 Command Center (Chennai).** Click the crisis countdown. Show the trace panel: metric, formula, inputs, source, status. "Every number says where it came from and whether it is reported, estimated or modelled."
**0:50 Data Health card.** Backend syncs rainfall every 20 minutes; failures are shown, not hidden. Point to what is NOT connected.
**1:10 Why + Monte Carlo.** Counterfactual attribution: reset each driver, rerun. "Estimated contribution, not proof of cause."
**1:35 Zone click.** Groundwater risk, 7-day rain, recommended actions.
**1:55 Save the City.** Apply the live rainfall anomaly (or set rain -20%, demand +15%), press Optimize. Read before/after horizon and cost index.
**2:30 Action plan.** 24h / 7d / 30d / 90d plan.
**2:45 Validation + limits.** Mumbai 2026 backtest, leave-one-report-out check, three reports only. Then the pilot plan: 12 weeks, shadow mode.
## Q&A
- *Is it real data?* Rainfall: real public feed (Open-Meteo reanalysis, not gauges). Reservoir capacities: reported. Levels: reported for Mumbai, Visakhapatnam, Chennai (undated report); assumed for the rest. Demand/supply: estimates. Zone and groundwater depths: indicative until CGWB data is connected.
- *Does it actually alert anyone?* Yes. When a city turns red (projected failure inside 14 days) the backend sends one SMS to the three control-room numbers, repeats at most daily, retries failures, and logs every attempt. Lower levels never send. It runs in dry-run until provider keys are set, and the admin-only test button proves delivery.
- *Is it machine learning?* Two layers by design. A water-balance engine explains causes and tests what-if scenarios. A learned model (quantile gradient boosting with conformal-calibrated bands) forecasts reservoir storage 1 to 4 weeks ahead and is backtested on CWC history against three baselines. Say the real skill numbers only after `scripts/run_backtest.py` has run on real bulletins; show the Validation tab card.
- *How accurate?* Read it from the Validation tab: rolling backtest on N weekly CWC bulletins, error vs three baselines with 95% intervals, band coverage, and alert recall on onset events. Where the interval includes zero we say so. The pilot re-measures it on the utility's own history. (Older city backtests: Mumbai 2026 and Chennai 2025-26, three reports each, a first check only.)
- *Why trust you?* We show staleness and gaps ourselves.

## Voice demo
Use the header button 'Guided demo'. 14 steps, about 3 minutes at the default 1x speed (v5.10). Space pauses, arrows move between steps, Esc exits. Do a sound check on the venue laptop; if audio fails, the captions still run.

## Data honesty slide
Open the Data & Sources tab and say: live rainfall only when the backend runs; reservoir levels are reported snapshots with dates; demand, supply and groundwater are estimates; CGWB, India-WRIS and IMD gauges are not connected.

## Red Alert Demo page (30 seconds)
Open 'Red Alert Demo', press 'Play: conditions worsen'. Say: "Every number on this page is generic and labelled GENERIC; it only shows what a red alert and the commissioner's message look like. Every other page uses real inputs or labels what is estimated."

## Impact answer (30 seconds)
See docs/IMPACT_AND_PILOT.md. Lead with the measured lead time on onset events, the 12-week shadow pilot with fixed success metrics and a stop rule, and one real conversation with a utility engineer if you have it.

## Order for the ML slide
Problem: weekly bulletins are read by hand. Method: learned model + band. Test: rolling backtest, no look-ahead. Result: skill vs strongest baseline with its interval, band coverage, onset-event recall. Limit: stated automatically in the report. Never show a number that is not in `data/ml_report.json`.
