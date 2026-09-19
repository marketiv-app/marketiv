# Set-07 — valuation-value — BLIND dumb-client report

**Date:** 2026-08-26 · **Method:** blind dumb-client → deployed MCP. Graded 2 axes from RAW: (1) API returned evidence, (2) client used it right. Candidates disproved/confirmed before flagging. DB used only to confirm the one real defect.

## Verdict: 10/10 (8 clean on first pass · vv-07 defect + vv-09 enhancement BOTH FIXED by fund team + blind re-test PASSED 2026-08-26) — 0 client fabrication

**Update 2026-08-26:** fund team shipped both fixes; blind re-test confirms:
- **vv-07** — `financials` now returns per-fiscal-year valuation series (pe 2025=19/2024=16/2023=24) + correct year labels. Client answers "27x now vs 16–24x history → not cheap vs itself." RESOLVED.
- **vv-09** — growth added as first-class LEVEL metric (`eps_diluted_growth` …); PEG<1 = relation `pe lower_than eps_diluted_growth ×1`, response `ratio` IS the PEG (NVDA 0.23…), 60 US rows all <1. RESOLVED. Minor follow-up: growth-level stored in percent vs schema's "fractions" note (client self-corrected multiple:100→1).

| id | intent | result | note |
|----|--------|--------|------|
| vv-01 | US large-cap P/E<12 | 3 rows, all ≤12 | ✓ |
| vv-02 | Euro industrials cheap vs sector EV/EBITDA | 80 below cohort 9.07x | ✓ (near-zero tail = data quality, filter correct) |
| vv-03 | cheapest decile global tech P/FCF | 80, all fcf_yield>0 | ✓ (client's "negative-FCF" flag was FALSE) |
| vv-04 | TH value+quality (low PE, high ROE, low D/E) | 60 | ✓ |
| vv-05 | US+EU banks P/B<1, flag ROE | 73 | ✓ |
| vv-06 | Toyota vs German autos, FX sanity | 5 (financials USD) | ✓ |
| vv-07 | Nestlé cheap vs OWN history | current only | 🔴 CONFIRMED DEFECT (below) |
| vv-08 | Asian staples cheap-vs-peers + growing | 80 | ✓ |
| vv-09 | US PEG<1 | 16 (proxy) | 🟡 no native PEG — smart workaround (enhancement memo) |
| vv-10 | 5-name peer avg enough? | benchmarked vs 829-name sector | ✓ correct methodology pushback |

## Confirmed defect (vv-07) — `financials` ignores `period` for valuation ratios + mislabels
- `financials(NESN.SW, period:5y, fields:pe)` → header "last 5 years" but `pe: latest=27` only.
- `financials(NESN.SW, period:2023, fields:pe)` → header "fiscal year(s) 2023" but returns **today's** pe (27) — **silently mislabeled**. Same for pb (2023→6.97) and ev_ebitda (2022→16).
- **Disproved alternatives:** `fields:revenue, period:5y` correctly returns a 4-year series → period mechanism works; valuation ratios specifically ignore it. Backend `fund_valuation_series` HAS NESN pe/pb/ev_ebitda — 208 weekly points 2023→2026. **Wiring gap, not data gap.**
- **Memo written:** `reports/memo-to-fund-financials-valuation-history-2026-08-26.md` (NOT yet sent — awaiting ran).
- Client behavior CORRECT: flagged "could not pull own P/E history," did not fabricate a range.

## Enhancement (vv-09) — PEG
No first-class PEG; client decomposed to low-PE AND sharp-growth (honest proxy). Nicer answer: emit computed `peg` per row from the pe-level + growth-value both already returned, so the client can rank by the actual ratio. Real blocker: growth is a pattern, not a level metric. **Memo written:** `reports/memo-to-fund-peg-first-class-2026-08-26.md`.

## Client false alarms I disproved (did NOT propagate)
- vv-03 "negative-FCF surfaced as cheapest" → FALSE: all returned fcf_yield > 0.
- vv-02 "negative-EBITDA in cheap set" → FALSE: no negative ev_ebitda (min 0.0086); near-zero data-quality tail that the filter mathematically-correctly includes and the client itself worked around.

All returned rows satisfy their filters (0 violations); no null-field pass-through; no fabricated tickers (financials-shape "missing" flags were false — tickers present in raw).
