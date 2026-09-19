# run05 — 2026-09-19 · POST-FIX re-run of run01's 24 cases (diff vs run01)

**Code:** mdx-api `9bd5a1bf+dirty +run03` (DPS strip) · mcp-jev `3717851+dirty +run02` (ticker returns row ticker) · Jev `…f2f2ec`
**Server pre-verified** healthy (:8902→:8090, NVDA→NVDA.US, DPS stripped) BEFORE spawn. All 4 blind agents held server discipline (only :8902, no improvising). run04 was INVALID (server was down → agents hit prod).

## Tally: **24 PASS · 0 PARTIAL · 0 FAIL**

## Diff vs run01 (the 2 PARTIALs + the phantom defect — all resolved)
| case | run01 | run05 | fix |
|---|---|---|---|
| **t12** (NVDA compare) | PARTIAL — NVDA→**NVDA.SW** (Swiss) | PASS — NVDA→**NVDA.US** | run02 (_resolve_ticker returns row ticker, not matched_via) |
| **f03** (AMD R&D/capex) | PARTIAL — AMD→**AMD.XETRA** | PASS — AMD→**AMD.US** | run02 |
| **t02** (ปตท. cashflow) | PASS + defect: phantom **2004/2003/2002** columns | PASS — **no pre-2010 columns** | run03 (strip dividend_per_share from statement grid) |
| **t03** (TSMC balance) | PASS + phantom | PASS — clean | run03 |
| **f02** (MSFT cashflow) | PASS + phantom | PASS — clean | run03 |

## Everything else held (no regression)
- Identity: ปตท.→PTT.BK · 茅台→600519.CG · Samsung→005930.KO · TSMC→2330.TW · BRK.B→BRK-B.US · KBANK→KBANK.BK · Bitcoin→no_match.
- fsconcept: near-dup (EPS basic/diluted, goodwill/intangibles, treasury vs buyback) · no-match (analyst target, ESG) · gross-loss fold · granular (accrued interest, construction in progress).
- No fabrication.

## Residual (NOT bugs)
- **f01** "[income] line-items show 2022/2021": annual statement's latest COMPLETE year is FY2025 (Sep); digest as-of is Q2-2026 (quarterly). Different granularity, both correct — verified via raw JSON (income latest = 2025-09-30). Agent misreads the text table's column order; not a data error.
- **2025-12 empty column** (ปตท.): the not-yet-filed current fiscal year appears as an empty header — legitimate, not a phantom.

## Conclusion
Both fixes land through the real MCP; the resolver axis (fsconcept + ticker) is now **24/24 clean**. No open resolver defects.
