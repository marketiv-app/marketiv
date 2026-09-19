# set-01 (technical-novice) — MCP test report

**Method:** blind dumb-client ran all 10 cases over the real MCP (raw responses saved to `raw/set-01/`). Grading is done **from the API responses alone** — I know the input the client sent (= the API input, MCP relays 1:1) and the API returns the evidence it screened on (`context.ta`, `matched.ta` values), so result-correctness is checked by confirming that returned evidence satisfies the input condition. No DB re-query needed.

## Totals — 3 axes
- **right_tool: 10/10** — every case picked a sensible tool + args (find_* resolver → screen_unified / asset_pulse / macro_pulse).
- **result_correct: 10/10** — returned rows' evidence satisfies the asked condition (see per-case). One design nuance on tn-10 (below).
- **explanation_correct: 10/10** — each `answer_to_user` matches the evidence (notably tn-10: the client excluded recovered names on its own).

## Per-case (result_correct — checked from the API's own returned evidence)
| id | condition | check from response | verdict |
|----|-----------|--------------------|---------|
| tn-01 | RSI>70 | all 60 rows `context.ta.rsi14` > 70 | PASS |
| tn-02 | at 52w high | all 3 carry `matched.ta.at_new_high` | PASS |
| tn-03 | golden cross | 59/59 `cross_ema50_ema200_up` with a≥b (ema50≥ema200) | PASS |
| tn-04 | TSLA over/oversold | asset_pulse fields consistent w/ narration (below 50/200d, −30% off high) | PASS |
| tn-05 | dropped but fine | 60 rows, `matched_legs=[fundamental,ta]`, `net_change_down.ret`<0 | PASS |
| tn-06 | squeeze | 60/60 carry `bb_sqz`, low atr_pct | PASS |
| tn-07 | crypto near low | all `.CC` + `near_low` on every row | PASS |
| tn-08 | tech up + volume | `net_change_up.ret`>0 + a volume signal present | PASS |
| tn-09 | bullish MACD cross | macd≥signal where detail present; 4 rows have null detail (event only, current state not in payload) | PASS |
| tn-10 | broke below 200-day | 17/21 have `close_vs_ema200`<0; **4 (MO/ETR/CTVA/VALE) are ABOVE** — matched the cross-DOWN *event*, since recovered | PASS* |

## Findings
1. 🟡 **Event-signals return "recently crossed", not "currently below" (tn-10).** `cross_close_ema200_dn` matches a stock that crossed below ema200 within the window even if it has since recovered above — so 4/21 rows sit above their 200-day. NOT an API error: the row is a correct event match and the response transparently exposes `context.ta.close_vs_ema200` (positive for the recovered ones), which the client correctly used to list only the genuinely-below names. A caller wanting *current* weakness should screen the STATE (`close_below_ema200`) rather than the cross event. Worth a one-line schema hint (event vs state).
2. 🟡 **tn-09 null matched detail** for a few rows — the crossover event is surfaced but not the current macd/signal values, so "still bullish now" can't be confirmed from the payload alone (same event-vs-state theme).
3. 🟢 Deployed this session and exercised here: `matched.ta` keyed by pattern TOKEN (verified: `rsi14_above_70`, `cross_ema50_ema200_up`, `net_change_down`, `near_low`, `macd_x_signal_up`, `close_below_ema50`), symmetric with `matched.fundamental`. The `within`-display fix (co-occurring vs all-time-biggest event) is deployed but not exercised in this run (tn-08 used `rising_volume`, not volume_spike+within).

**Bottom line:** set-01 is clean on all three axes. The only substantive note is the event-vs-state semantics on tn-10/tn-09 — correct results with honest evidence, but a schema hint would stop a naive caller from reading a recovered name as "currently below."
