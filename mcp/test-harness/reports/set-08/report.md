# Set-08 — thematic-macro — BLIND dumb-client report

**Date:** 2026-08-26 · **Method:** blind dumb-client → deployed MCP. Graded 2 axes from RAW + DB/source cross-check to confirm/disprove candidates.

## Verdict: 1 CONFIRMED high-impact defect (theme_players drops mapped leaders) + minors. Non-theme tools clean.

| id | intent | tool(s) | result |
|----|--------|---------|--------|
| tm-01 | HBM players | find_megatrend + theme_players | ✓ populated |
| tm-02 | cheap Asian semis (low P/E) | screen_unified | ✓ 60, all pe>0 |
| tm-03 | US yield curve / 2s10s / MM rates | bond_pulse | ✓ curve+spread returned |
| tm-04 | EU defense names | theme_players | 🔴 Leonardo/Saab DROPPED (below) |
| tm-05 | gold + miners | commodity_pulse + theme_players | ✓ |
| tm-06 | small-cap China biotech | screen_unified→screen_stocks | 🟡 no size-tier filter; fell back, 25 rows |
| tm-07 | uranium/nuclear players | theme_players | ✓ (Kazatomprom has no clean listing) |
| tm-08 | USD vs EUR/JPY/CNY + oil | find_stock + stock_prices_batch + commodity_pulse | ✓ (USD/CNY needed 1 retry) |
| tm-09 | GLP-1 players | theme_players | 🔴 Novo Nordisk DROPPED (below) |
| tm-10 | copper backdrop + cheap miners | commodity_pulse + theme_players + screen_unified | ✓ leaf; 🟡 parent node no-rollup |

## 🔴 CONFIRMED DEFECT — `theme_players` silently drops companies that ARE mapped as core leaders
Verified against DB (`listing_megatrend`) + news-api source (`megatrend.rs`):
- **Novo Nordisk** — `role=leader, exposure=core` on node 18010000 (Metabolic/Diabetes/Obesity, via NOV.XETRA) and on 34070000 (GLP-1 Healthspan, via NVO.US) — returned by `theme_players` for NONE of 18010000/{US,DE,DK} or 34070000/US. The #1 GLP-1 name is invisible in its own theme.
- **Leonardo & Saab** — both mapped to 22020000 (Defense Primes — Europe & Asia) — absent from `theme_players(22020000, GB)`.
- **Root cause (Leonardo/Saab, confirmed):** the membership CTEs exclude LSE/XETRA `0`-prefix foreign lines BEFORE resolving to the canonical head (`megatrend.rs` L79/L356). Leonardo's only mapping is on `0ONG.LSE` (0-prefix) → dropped, with no home-exchange mapping to fall back to. Novo passes that filter on NOV.XETRA yet is still dropped by the country handler — last hop not fully traced.
- **Impact:** this is the persona's CORE query. A blind client concluded "Novo isn't in this theme" (false). The blind client's *conclusion* (names absent from output) was CORRECT; its *explanation* (domicile scope / not members) was wrong.
- **RCA (ours to fix):** `reports/RCA-theme-players-drops-mapped-leaders-2026-08-26.md` — traced end-to-end (data → endpoint → tool). Root = `data.rs` `co` CTE anti-cross-listing filter (`ISIN-country ≠ exchange-country`) eliminates a company whose only head is a foreign hub-line; Novo (DK-ISIN on XETRA), Leonardo (IT-ISIN on LSE). Layered on a DATA gap (no home .CO/.MI listing) + TOOL under-exposure (country required, no `all`).

## Client false-lead corrected
The client framed this as "theme country scope is domicile-based and misses foreign members / Novo not a member." Disproved: Novo IS a core leader in the theme; the tool drops it. Reported the confirmed tool behavior, not the client's explanation.

## Minor observations (not memo-worthy alone)
- **tm-10 parent-node no-rollup:** `screen_unified(theme:30020000)` (copper parent) → count 0; only the leaf `30020100` has members. Parent theme nodes don't aggregate children. Same family as the dropped-leaders issue.
- **tm-06 size-tier:** `screen_unified` rejects a filter-only universe list (gics+country+size, no fundamental/TA condition); `screen_stocks` has no size-tier param → "small-cap" isn't first-class on either path. Client fell back and read market caps.
- **tm-08 USD/CNY:** `find_stock` batch first returned bond/spread names for "USD/CNY"; a reworded single query resolved USDCNY.FOREX. One retry, self-corrected.

## Clean
Non-theme macro tools all returned correct data and were narrated faithfully: bond_pulse (yield curve/2s10s), commodity_pulse (gold/copper/oil), stock_prices_batch (FX), screen_unified valuation (semis 60 rows, all pe>0).
