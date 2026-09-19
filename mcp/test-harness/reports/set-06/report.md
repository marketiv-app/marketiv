# Set-06 — income-dividend — BLIND dumb-client report

**Date:** 2026-08-26 · **Method:** blind dumb-client (mcp_call.py → deployed marketdx-mcp). Graded 2 axes FROM RAW (`raw/set-06/id-*.json`): (1) did the API return the evidence, (2) did the client use it correctly. Ticker citations cross-checked by script; key numbers spot-verified vs raw. DB not needed.

## Verdict: 10/10 tool-correct — 0 API/tool defects. One client-narration typo (not a tool defect).

| id | intent | tool | api returned | client narration |
|----|--------|------|--------------|------------------|
| id-01 | highest yields in world | screen_dividends | 20 rows + `_guide` trap-decomp | ✓ numbers exact; ⚠️ 1 ticker typo (below) |
| id-02 | safe 5-7% yield, payout not stretched | screen_dividends (min/max_yield, max_payout) | 20 | ✓ |
| id-03 | growing dividend (CAGR) | screen_dividends order_by cagr | 20 | ✓ |
| id-04 | aristocrats 25y+ streak | screen_dividends | 20 + streak capped at 10 | ✓ correctly REFUSED to claim 25y (honesty) |
| id-05 | 9% telecom down 40% — trap? | screen_dividends (telecom cohort) | 10 | ✓ decomposed trap-vs-safe |
| id-06 | Asia REIT+utility, no-cut (TH) | find_gics ×2 → screen_dividends | 20 | ✓ |
| id-07 | banks vs utilities vs REITs by country | find_gics → screen_dividends ×3 | 15×3 | ✓ |
| id-08 | yield meaningfully > 4.3% UST, safe | screen_dividends (min_yield 6, payout+streak gates) | 20 | ✓ |
| id-09 | is XYZ's dividend safe? | (none — placeholder) | — | ✓ correctly asked for real ticker |
| id-10 | never-cut + rising dividend (TH) | screen_dividends (streak 10 + cagr>0) | 20 | ✓ |

## Axis 1 — API returned evidence: YES, and well-structured
`screen_dividends` is well-built for this persona: one screener with `min_yield`/`max_yield`/`max_payout`/`min_streak_years`/`min_cagr`/`order_by`, rows carry nested `dividend:{yield_pct, yield_trailing_pct, cagr_5y_pct, no_cut_streak_yrs, last_cut_year, payout_ratio, ffo_payout, ttm_div_yoy_pct}` + `_guide` that enforces trap-decomposition (forward vs trailing = special div; payout>1 = unsustainable; price-drop + neg news = trap). The `no_cut_streak_yrs` caps at 10 and the `_guide` explicitly forbids claiming a multi-decade aristocrat streak — which is exactly why id-04 could not be answered wrongly.

## Axis 2 — client used it right: faithful, one typo
Ticker cross-check (script): all cited tickers present in responses EXCEPT id-01's `2333.HK`. Verified: the response row is **2139.HK — Bank of Gansu**; the client wrote "Bank of Gansu (2333.HK-area)" — correct NAME + correct numbers (yield_pct 37.4 fwd / 49.37 trail, special-div inference right), but WRONG ticker digits, hedged with "-area". This is a **dumb-client narration slip on the id, not an API/tool defect** — the tool returned 2139.HK correctly. All other id-01 numbers verified exact vs raw (LHRREIT 46.76, HUYA 45.79 + cut 2025 + ttm −94.7% + eps −0.07, NH Prime 45.43 + cut 2022 + PE 480).

## Candidates raised & disproved
- **id-01 `2333.HK` cited-not-in-response** → NOT a tool defect. Client misquoted 2139.HK's digits (name + all figures correct, grounded in raw). Client error, hedged.
- **id-09 no data pulled** → NOT a defect. "XYZ" is a placeholder; client correctly requested the real ticker rather than fabricate one.

## Minor observation (not a defect)
REIT `payout_ratio` is EPS-based and looks alarming for REITs (they distribute cash flow); `ffo_payout` exists for the correct lens but was null on the sampled REITs → client caveated verbally. Coverage thinness on `ffo_payout`, not a defect.

No memo, no outward broadcast. Nothing to fix in set-06.
