# RCA (OURS to fix) — `theme_players` drops mapped core-leaders (Novo, Leonardo, Saab)

**Date:** 2026-08-26 · **Owner:** TA/MCP (this is our endpoint+tool+data, NOT a fund-team item) · Traced end-to-end from MCP tool → news-api endpoint → SQL → DB rows.

## Observable
`theme_players(theme, country)` returns none of: Novo Nordisk (core-leader on 18010000 Metabolic/Obesity AND 34070000 GLP-1) for any country; Leonardo / Saab (mapped to 22020000 EU Defense Primes) for GB. The membership DATA is correct — the serving path drops them.

## The three layers, exact

### Layer 1 — DATA (ava_listings): missing home listings → canonical head is a foreign cross-listing
- Novo Nordisk has **no Copenhagen (.CO) listing** in `ava_listings` at all. Its listings are NOV.XETRA, 0QIU/0TDD.LSE (0-prefix), NVO.US (ADR), NOVOB80.BK. `canonical_listing_id` resolution therefore makes **NOV.XETRA (243294) the head** (NVO.US.canonical → 243294).
- Leonardo has no Milan `.MI` listing mapped; its theme membership + head is **0ONG.LSE** (a 0-prefix LSE line). Saab: same via 0GWL.LSE.

### Layer 2 — ENDPOINT (`services/news-api/src/data.rs`, `megatrend_stocks`, `co` CTE ~L326-331)
```sql
WHERE h.is_active AND asset_type='Common Stock'
  AND COALESCE(hm.home_category,'') NOT IN ('ADR','GDR')
  AND NOT ( h.exchange_code IN ('LSE','XETRA') AND (
        h.symbol ~ '^0' OR h.currency NOT IN ('GBX','GBP','EUR')
        OR (h.isin IS NOT NULL AND LEFT(h.isin,2) <> he.country_iso2) ) )   -- ← the killer
```
This filter runs on the **company HEAD** `h`. Confirmed against DB:
- NOV.XETRA: ISIN `DK0062498333` (DK) on XETRA (country DE) → `LEFT(isin,2)='DK' <> 'DE'` → `survives_co_filter = FALSE`.
- 0ONG.LSE (Leonardo): ISIN `IT0003856405` (IT) on LSE (GB) + 0-prefix → `FALSE`.
- NVO.US route dies on `home_category IN ('ADR','GDR')`.

The filter's INTENT is to drop duplicate foreign hub-lines when a domestic line also exists. The BUG: when the company's **only head is a foreign hub-line** (no domestic listing in the data), the filter eliminates the **entire company** from the theme — even though it's a mapped core leader. (LLY survives only because its head is domestic LLY.US; its XETRA line is merely the country representative.)

### Layer 3 — TOOL (`marketdx/mcp/server.py`, `theme_players`)
- Marks `country` **REQUIRED** and does not expose the endpoint's `country=all` (global roster) or `rollup`. So a client can't pull the roster that ignores country, and must guess — compounding invisibility. (Note: `country=all` would NOT rescue Novo anyway — it's dropped in `co`, before the `cand` country filter — so Layer 2 is the primary bug.)

## Fix plan (ours)
1. **ENDPOINT (primary):** don't let the anti-cross-listing filter ZERO OUT a genuinely-mapped company. Options: (a) apply that filter only to CHOOSE the display representative among ≥2 candidate listings, never to eliminate the company; or (b) if every candidate listing for a mapped company fails the filter, FALL BACK to the best foreign line (canonical head) rather than dropping it. Net: a company mapped to a theme must always appear at least once.
2. **DATA (durable):** backfill the missing home listings (Novo Copenhagen `.CO`, Leonardo Milan `.MI`) so the canonical head is domestic and passes the filter naturally. Broader ingestion audit: how many theme members have only a foreign-hub head?
3. **TOOL:** make `country` optional / expose `country=all` in `theme_players` so the global roster is reachable, and document that membership is per-company (not per-country-listing).

## Repro
```
theme_players {theme:"18010000", country:"DE"}   # 7 US-pharma XETRA lines, NO NOV.XETRA
theme_players {theme:"22020000", country:"GB"}   # 10 EU primes, NO Leonardo(0ONG.LSE)/Saab(0GWL.LSE)
# DB: NOV.XETRA→18010000 core/leader; ISIN DK on XETRA(DE) → co-filter FALSE (confirmed)
```
