# Impact and pilot plan

Fill the brackets with sourced numbers; every number must carry a source and a date. Do not present any bracket as fact until it is filled.

## 1. Who is helped
- Residents served by the pilot city: `[N million]` (cities.json pop_m is the starting point; cite the utility's own coverage figure).
- Control-room staff who today read a weekly bulletin by hand: `[N people, source: interview]`.

## 2. What an earlier warning is worth (transparent arithmetic)
`value per event = weeks of extra warning x weekly cost avoided`
- Weeks of extra warning: measured by the backtest as lead time on onset events (`ml_report.json`, onset_only), not assumed. `[x weeks at 2-week horizon]`
- Weekly cost avoided: choose the utility's own cost lines, each with a source: emergency tanker hiring `[Rs/week]`, deferred-maintenance premium `[Rs/week]`, avoidable restriction days `[days x Rs]`.
- Show a low / base / high case. If the backtest gives no proven lead time (skill interval includes 0), say so and present the warning-and-explanation value only.

## 3. Pilot (12 weeks, shadow mode, no operational risk)
| Weeks | Activity | Output |
|---|---|---|
| 1-2 | Data-sharing agreement; load the utility's reservoir levels (CSV upload already supported) | Calibration data |
| 3-4 | Calibrate and re-run the backtest on the utility's own history | Utility-specific accuracy report |
| 5-10 | Shadow mode: send weekly forecasts and alerts alongside the control room's normal process; no action required | Log of alerts vs what happened |
| 11-12 | Review with the control room | Go / no-go and a written lessons list |

**Success metrics, fixed in advance:** onset-event recall >= `[x]%` at 2 weeks; at most `[1]` false alarm per reservoir-month; 80% band covers 75-85% of outcomes; alert read by a human within `[10]` minutes; operators rate the explanation useful (>= `[4/5]`).
**Stop rule:** if two consecutive monthly reports show skill vs the strongest baseline not above 0, stop and publish the result.

## 4. Cost to run (public data only)
Hosting `[Rs/month]`, SMS/WhatsApp `[Rs per alert x expected alerts]`, maintenance `[hours/month]`. Source: provider price pages, dated.

## 5. Who pays and who uses it
User: utility control room, state water-resources department. Payer options: utility subscription, state programme, grant/CSR. Citizen alerts as a free public layer (no payer needed).

## 6. Evidence of demand (the most valuable thing you can add)
Record at least one real conversation: name/role, date, what they said, what they would need to try it. A single quote with permission beats any slide. `[ ]`

Draft first message to a municipal or water-board engineer:
> Hello, I am `[name]`, a student/engineer building a free early-warning tool that reads the CWC weekly reservoir bulletin and flags reservoirs likely to fall below normal 1 to 4 weeks ahead, with an uncertainty band and a plain explanation. I would value 15 minutes of your view: what do you check today, what would make a warning useful to you, and would a shadow-mode trial be possible? I can share the backtest and the model card beforehand.
