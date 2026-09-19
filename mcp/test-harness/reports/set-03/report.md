# set-03 (fundamental-novice) — MCP test report

**Method:** blind dumb-client ran all 10 over the real MCP (raw in `raw/set-03/`). Graded from the API responses alone (input known = API input; API returns the evidence it screened on). No per-row DB re-query.

## Totals — 3 axes
- **right_tool: 10/10** — screen_unified / screen_dividends for screens; find_stock→financials→asset_pulse for single-name ("is Apple/Tesla…"); bond_pulse (bonds) + commodity_pulse (gold) for asset-class asks.
- **result_correct: 10/10** — returned evidence satisfies each ask (verified from matched.fundamental / the dividend block / the single-name digests).
- **explanation_correct: 9.5/10** — one slight over-claim (fn-05).

## Per-case (from API evidence)
| id | ask | evidence | verdict |
|----|-----|----------|---------|
| fn-01 | big well-known, cheap | matched.fundamental pe: GOOG 17.1, AMZN 21, META 20.5 (large-caps, low GAAP pe) | PASS |
| fn-02 | good + safe dividend | yield 4.6-6.1%, payout 0.37-0.75, **10y no-cut streak** (PFE/GIS/EPD/VZ/KMB) | PASS |
| fn-03 | is Apple expensive? | financials digest P/E ~35x → "fully priced but quality-justified" | PASS |
| fn-04 | profits up every year | net_income improved_every_year N=3 (NVDA/GOOG/MSFT…) | PASS |
| fn-05 | TH stable + dividend, long-hold | 2 rows: AMATA 4.0% / CPN 3.6% — BUT recent cuts (2021/2022), streaks 4y/3y | PASS* |
| fn-06 | low debt + good returns | D/E 0.06-0.18 + ROE 30-82% (NVDA/GOOG/MSFT) | PASS |
| fn-07 | is Tesla a good company? | digest P/E ~312x, profit −47%, strong balance sheet + FCF → balanced | PASS |
| fn-08 | quality (4 ANDed) | matched carries all 4: D/E + pe + revenue-growth + roe | PASS |
| fn-09 | safe non-stock (bonds) | bond_pulse: US curve 3.8-5.2%, positioning → bonds/bond-ETFs | PASS |
| fn-10 | gold safe haven? | commodity_pulse GOLD.COMM +40%/1y, −16% off high → pros/cons | PASS |

## Findings
1. 🟡 **fn-05 explanation over-claim.** The Thai stable-dividend screen returned AMATA (last cut 2021, 4y streak) and CPN (last cut 2022, 3y streak); the narration said "จ่ายต่อเนื่องหลายปี" (paid consistently for years) — a stretch given both cut within the last 3-4 years. Two views: (a) narration should note the recent cut for a "stable/long-hold" ask; (b) the dividend screen's streak threshold is lenient (lets 3-4y streaks with a recent cut through) — for a "safe/stable" intent a longer no-cut requirement fits better. Both are minor / fund-side.
2. 🟡 **Schema clarity (client recovered):** `bond_pulse` and `commodity_pulse` require param `q` (concept/ticker string), NOT `ticker` — the client's first attempts 400'd (`Field required: q`) then corrected. A one-line schema hint (or accepting `ticker` as an alias) would remove the round-trip. (marketdx MCP side.)
3. 🟢 matched.fundamental is well-populated and token-keyed (pe / net_income / debt_to_equity / roe / revenue), cohort context present (ctx.pe normalized_pe). Dividend block is rich (yield_pct, payout_ratio, no_cut_streak_yrs, cagr_5y, last_cut_year) — enough to substantiate every claim.

**Bottom line:** set-03 clean on tool + result; one minor narration over-claim (fn-05) and one schema-clarity nit (bond/commodity `q`). No hard defect.
