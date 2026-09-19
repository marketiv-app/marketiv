# Set-05 — combined-ta-fundamental — BLIND dumb-client report

**Date:** 2026-08-26 · **Method:** blind dumb-client (mcp_call.py → deployed marketdx-mcp → news-api). Graded 3 axes FROM RAW (`raw/set-05/cf-*.json`); DB re-query only to disprove candidates. No hints given to client.

## Verdict: 10/10 clean — 0 confirmed defects

| id | intent | count | tool | result | explain |
|----|--------|-------|------|--------|---------|
| cf-01 | net_income>0 ∩ rev CAGR>20% ∩ close×ema50 cross-up | 40 | ✓ | ✓ | ✓ |
| cf-02 | (fund ∩ ta) | 17 | ✓ | ✓ | ✓ |
| cf-03 | (fund ∩ ta) | 16 | ✓ | ✓ | ✓ |
| cf-04 | (fund ∩ ta) | 40 | ✓ | ✓ | ✓ |
| cf-05 | (fund ∩ ta) | 40 | ✓ | ✓ | ✓ |
| cf-06 | (fund ∩ ta) | 40 | ✓ | ✓ | ✓ |
| cf-07 | (fund ∩ ta) | 17 | ✓ | ✓ | ✓ |
| cf-08 | (fund ∩ ta) | 40 | ✓ | ✓ | ✓ |
| cf-09 | div_yield>3% ∩ dps improved 3y ∩ close×ema50 cross-up | **0 (partial)** | ✓ | ✓ | ✓ |
| cf-10 | (fund ∩ ta) | 40 | ✓ | ✓ | ✓ |

## Hand-check per condition (numbers visible — NOT a silent script)
| case | condition (verbatim) | value returned | verdict |
|---|---|---|---|
| cf-01 | net_income is_positive · revenue compound_growth≥0.2 | 9.55M · CAGR 0.2211 | ✓ · ✓ |
| cf-02 | pe below 15 | 11.75 | ✓ |
| cf-03 | net_margin **high** · debt_to_equity **low** | set bounded 0.133–0.801 · 0.000–0.040 | ✓ cutoff enforced |
| cf-04 | dividend_yield above 0.04 | 0.079 | ✓ |
| cf-05 | roe above 0.15 · revenue growth≥0 | 0.2595 · 0.231 | ✓ · ✓ |
| cf-06 | fcf_yield **high** | set bounded 0.075–1.118 | ✓ cutoff enforced |
| cf-07 | revenue above 1e9 · net_margin improved_every_year N=3 | 79.67B · [0.317>0.235>0.154] | ✓ · ✓ |
| cf-08 | net_income compound_growth≥0 | CAGR 1.0588 | ✓ |
| cf-09 | div_yield>0.03 · dps improved N=3 (∩ ta) | count=0 disjoint | ✓ legit empty |
| cf-10 | net_income growth≥0 · debt_to_equity **low** | 0.0308 · 0.0237 | ✓ · ✓ |

Qualitative `high`/`low` verified by the returned SET being cleanly bounded (all rows above/below a real cutoff), proving the filter ran. Server doesn't echo the exact bar in `matched`, but `context.fundamental` carries supporting numbers (pe/roe/margins/net_debt_ebitda) — evidence-rich, not a defect.

## How graded (both legs, from raw)
- **Fundamental leg** — per-kind read (`level→value`, `growth→value/window`, `relation→value_a/value_b/ratio`, `cohort→value/cohort_benchmark`). Checked returned evidence vs the condition the client sent. **fund_viol = 0** across all 290 full-match rows.
- **TA leg** — for each `matched.ta` token, checked directional consistency of `detail.a`/`detail.b` (up→a≥b, down/below→a≤b) and token presence vs the `crossover_up`/etc. the client sent. **ta_dir_viol = 0**.
- **Intersection integrity** — every non-partial row carries `matched_legs=['fundamental','ta']` (both legs actually matched). **leg_incomplete = 0**.
- **Evidence completeness** — every row has `ticker` + `name` + `head_listing_id` (+ `also_known_as` where cross-listed). Verified across 290 full + 6 near-miss rows.

## cf-09 — empty intersection is CORRECT, not a bug (disproved candidate)
Client sent a very tight fundamental pair (`dividend_yield>3%` ∩ `dps improved_every_year N=3`) intersected with `close×ema50 cross-up`.
- `legs: {fundamental: 1, ta: 359}` → the two id-sets are **disjoint** → intersection legitimately 0.
- Response sets `partial=True`, returns 6 TA-only near-misses each correctly labeled `matched_legs=['ta']` (NOT dressed up as full matches), and `notes` explains the disjoint + gives broaden guidance (loosen fundamental / widen `window_bars`).
- This is the designed partial-fallback behavior working exactly right.

## Candidates raised & disproved (per verify-from-raw rule)
1. **"full-match rows missing symbol" (290/290)** — FALSE. My check keyed `.symbol`; the field is `.ticker`. Re-read raw: `ticker:"2152.HK"`, `name:"Suxin Joyful Life…"`, `head_listing_id:52007` all present. My extractor bug, not a defect.
2. **cf-09 count=0** — disproved above (legit disjoint, correct partial fallback).

No memo, no outward broadcast. Nothing to fix in set-05.
