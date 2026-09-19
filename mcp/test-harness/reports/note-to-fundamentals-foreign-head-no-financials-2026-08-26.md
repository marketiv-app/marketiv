# Note → Fundamentals team — public companies whose only ava_listings head is a FOREIGN cross-listing get NO financials (missing from mv_head_metrics)

**From:** TA/MCP · **Date:** 2026-08-26 · **Found via:** thematic screener test (set-08) — flagship theme members invisible to fundamental screeners.

## The problem
Some large, genuinely public companies have **`fund_rows = 0`** (no `fund_facts` at all) → they're absent from `mv_head_metrics` → **any fundamental screener (`screen_stocks`, `screen_unified`) cannot return them**, and they carry no P/E, ROE, margins anywhere.

Confirmed examples:
| Company | ava_listings head | ISIN | fundamentals |
|---|---|---|---|
| Leonardo SpA (Italy) | `0ONG.LSE` (id 235197, canonical=null) | IT0003856405 | **0 rows** |
| Saab AB (Sweden) | `0GWL.LSE` (id 233993, canonical=null) | SE0021156726 | **0 rows** |

## Root cause
These companies DO have a head row in `ava_listings` — but the head is a **foreign cross-listing** (a `0`-prefixed LSE depositary line), NOT their home/primary listing:
- Leonardo's home line = **Milan `.MI`**, Saab's = **Stockholm `.ST`** — and those home listings are **NOT ingested into `ava_listings`**.
- Fundamentals sync keys off the home/primary listing (its native ISIN/ticker → Yahoo/EODHD). With no home listing present, there's nothing for the sync to pull → `fund_facts` stays empty → the company never enters `mv_head_metrics`.

Contrast: **Novo Nordisk** has the same shape (Danish co, foreign lines) BUT its `NOV.XETRA` head is a non-`0`-prefix line that DID get fundamentals → it IS in `mv_head_metrics`. So the gap is specifically companies whose ONLY head is a `0`-prefix / foreign depositary line.

## Impact
- These names are complete black holes for valuation/quality: no P/E, P/B, ROE, margins, growth — invisible to every fundamental screen and to "cheap/quality" questions.
- They still show up correctly in the **membership roster** (`theme_players`, which sources `listing_megatrend` directly, no fundamentals needed) — so the theme knows they exist; only the financials are missing.

## Ask (fundamentals team)
Find a way to ingest financials for companies whose ava_listings head is a foreign cross-listing. Options to consider:
1. **Add the missing home listings** (Leonardo `.MI`, Saab `.ST`, etc.) to `ava_listings` and re-point canonical/head to them → sync then pulls financials natively (also fixes the head-quality issue elsewhere).
2. **Fundamentals-sync fallback**: when a head is a `0`-prefix/foreign line with no financials, resolve the issuer by ISIN (e.g. `IT…`→Milan, `SE…`→Stockholm) and pull financials by ISIN/home-ticker, attaching to the existing head.
3. Audit scope: how many `listing_megatrend` / active-listing heads are `0`-prefix-LSE / foreign-only with `fund_rows=0`? (This is the size of the coverage hole.)

## Not us / already handled on our side
- Theme membership + roster surfacing is fixed on our side (theme_players now returns these names). This note is ONLY about the missing FINANCIALS for foreign-head companies — that's the fundamentals pipeline's call.
- NOT an off-coverage/private-company case — these are listed public companies with a real ava_listings head; the head is just the wrong (foreign) line.
