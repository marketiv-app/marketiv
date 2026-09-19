# run02 — 2026-09-19 · targeted fix-verification (NOT a full blind loop)

**Fixes run01 defect #1** (wrong-listing: NVDA→NVDA.SW, AMD→AMD.XETRA).

## Root cause
`/v1/stocks?q=NVDA` correctly returns `ticker=NVDA.US` but with `matched_via=NVDA.SW` (metadata: a Swiss
cross-listing NVDA.SW also matched, its head is NVDA.US). `_resolve_ticker`'s `_via()` helper WRONGLY preferred
`matched_via` over `ticker` as the returned identity — so it returned NVDA.SW. The assumption "matched_via = user
intent" was false: matched_via is just *whichever secondary lexically matched* (GOOGL's happened to be the intended
US Class-A line; NVDA's is a foreign Swiss line).

## Fix (mcp-jev/server.py `_resolve_ticker`)
Return the row's `ticker` (the canonical/primary listing /v1/stocks chose) ALWAYS. Use matched_via ONLY to DETECT
the query hit (fast-path, via `_syms()` = {ticker, matched_via, symbol} bare symbols) + as Jev context. Never as the
returned ticker.

## Verified (bare symbol → resolved ticker)
| query | before | after |
|---|---|---|
| NVDA | NVDA.SW ❌ | **NVDA.US** ✅ |
| AMD  | AMD.XETRA ❌ | **AMD.US** ✅ |
| GOOGL | GOOG.US | GOOG.US (unchanged — canonical Class C, correct for financials) |
| RDDT | RDDT.US | RDDT.US ✅ |
| MSFT | MSFT.US | MSFT.US ✅ |

All fast-path `exact_symbol` conf 1.0. run01 t12/f03 PARTIAL → now would PASS.

## Note
GOOGL→GOOG.US is /v1/stocks' deliberate cross-listing canonicalization (Class A collapses to Class C head), correct
for financials (same head). If a price/pulse tool later needs Class-A precision, that's a /v1/stocks canonical
question — separate from _resolve_ticker.
