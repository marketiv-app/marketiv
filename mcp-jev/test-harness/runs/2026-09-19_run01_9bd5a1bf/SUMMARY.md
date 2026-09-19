# run01 — 2026-09-19 · resolver blind-client (fsconcept + ticker)

**Code under test:** mdx-api `9bd5a1bf+dirty` (anchored `/v1/stocks` + registry unify, debug :8090) · mcp-jev `3717851+dirty` (`_resolve_ticker` + financials one-param) · Jev key `…f2f2ec`
**Method:** 4 blind subagents, `financials` MCP tool, args client-chosen from `tools/list`/`schema`, natural Thai questions. Grader read `raw/` vs `testset acceptance` (never shown to client).

## Tally: **22 PASS · 2 PARTIAL · 0 FAIL** (24 cases)

## What worked (resolver axis = excellent)
- **Ticker identity:** Thai (ปตท.→PTT.BK), Chinese (茅台→600519.CG), Korea .KO (Samsung→005930.KO, not .KS), TW head (TSMC→2330.TW not TSM ADR), cross-listing (Alphabet→GOOG), **BRK.B dot-notation→BRK-B.US (the fixed case) ✅**, ambiguous KBANK→KBANK.BK, non-company Bitcoin→clean no_match.
- **fsconcept:** near-dup distinct (basic vs diluted EPS · goodwill vs intangibles · treasury vs buyback), no-match honest (analyst target · ESG · Bitcoin), gross-loss fold (→gross_profit), granular hard lines (accrued interest receivable · construction in progress), Thai→English translation by the client.
- **Regressions fixed, confirmed live:** allowance-class bug GONE (f05 accrued interest = honest unavailable, correct concept, NOT wrong 'receivables') · no false reconfirm (old GOOGL reconfirm resolved; Alphabet = soft-note, non-blocking).
- **No fabrication anywhere** — every absence stated honestly.

## Defects (all OUTPUT/data-plane or resolver-listing — NOT a resolve-correctness miss)
1. 🔴 **Wrong listing surfaced** (t12, f03): bare US-megacap → foreign cross-listing — **NVDA→NVDA.SW**, **AMD→AMD.XETRA** (not `.US`). Financials are correct (head-collapse hides it) BUT the returned ticker is a non-primary foreign line → **wrong if `_resolve_ticker` is reused for stock_prices/pulse** (GOOGL.US≠GOOG.US price logic). Investigate the fast-path/ranking — should prefer the primary/US listing among equal exact-symbol matches. → the 2 PARTIALs.
2. **Stale `[income]` line-item periods** (f01): digest as-of 2026-06 but the income line-item block shows 2022/2021 — inconsistent. `fund-backend`.
3. **Stray empty legacy-year columns** (t02/t03/f02): 2004/2003/2002 blank cols in whole-statement tables. Cosmetic, `fund-backend`.

## Next
- Fix #1 (wrong-listing) — likely in `_resolve_ticker` fast-path or `/v1/stocks` ranking for multi-market same-symbol; re-run **t12/f03** in run02 to confirm (diff dirs).
- #2/#3 are fund-backend statement-shape (separate from resolver); log, fix opportunistically.
- Then broaden: more sets (oppattern/tasignal/gics later per agreed sequence), and deliberately force a HARD reconfirm (two genuinely-close entities) to watch client↔MCP reconfirm behavior.
