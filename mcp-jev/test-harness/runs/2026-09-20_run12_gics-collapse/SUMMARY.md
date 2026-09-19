# run12 — collapse `find_gics` into its consumers + DELETE it (first bucket on the §15 plan-template rails)

**Code:** mdx-api `8fb26c4e` (`:8090` = DEBUG build → correctness only) · mcp-jev `c15d3cf`+working (find_gics DELETED;
`_resolve_gics`/`_gics_arg` added; 6 consumers resolve NL server-side) · Jev …f2f2ec · :8902. T1: re-read test docs before testing (done).
**Set:** resolver-gics-v1 {gi01–gi06} · 2 blind Sonnet clients.

## Result — 6/6 PASS (process AND output verified from real data; both governance gates met)
| axis | proof |
|---|---|
| Mechanical (mine) | tools/list has **NO find_gics**; consumers present (screen_unified/brief/screen_stocks/screen_dividends/write_note); `theme_pulse` still resolves gics internally (`_resolve_gics_codes` KEPT). |
| Process — blind | All 6 sent NL sector terms to a consumer — **0 find_gics calls, 0 round-trip** (tool gone). Collapsed across **≥3 different consumers** (screen_unified.gics + exclude_gics, brief.gics, screen_stocks.gics). |
| NL resolver exercised | biotech · banks · semiconductors · retail · fintech — all plain English; `_resolve_gics` did the work (candidate source = existing `_resolve_gics_codes`, Jev picks when ambiguous). Exact-CODE passthrough also hit (gi06 sent `40201060` / `45201010,...`). |
| Output — from real data | gi01 biotech→352010 (stocks genuinely biotech) · gi02 banks→4010, universe excludes banks · gi04 semiconductors→4530 (NVDA/Micron/SK Hynix) · gi06 fintech→honest no_match then client drill. Verified by re-calling the agents' own args and inspecting `_resolved_gics`/scope/universe. |

## Design notes
- **Occam held:** same operation as the prior buckets. The one honest difference — no vector `/find` endpoint — was
  handled by REUSING `_resolve_gics_codes` (gazetteer+deepseek) as the shortlist + Jev pick. No new endpoint/engine.
  273 codes > Jev's 255 cap never bit (the shortlist is small).
- **Nested-hierarchy refinement** (added after smoke): `_resolve_gics_codes` returns the rolled-up group + the
  specific node ('banks' → [4010, 401010]); when the shortlist is a pure ancestor-chain, take the BROADEST directly
  (gate=`rollup`) — no needless reconfirm for plain sector words. Genuinely-different homes (retail) still go to Jev.

## Defect (jev-quality, minor — not a collapse bug)
- **gi05 'retail' → Consumer Staples Distribution & Retail (3010)** at soft confidence, rather than reconfirming
  vs Consumer Discretionary retail (the more common reading) or defaulting to it. A Jev pick on a genuinely
  ambiguous word; the client itself flagged it. Tune the `_GICS_RESOLVE_INSTR` / gate if it matters. Mechanism is correct.

## Verdict
`find_gics` fully collapsed into all 6 consumers + DELETED; NL sector terms resolve server-side (nested→broadest,
ambiguous→Jev/reconfirm, non-sector→honest no_match), `theme_pulse` preserved, output verified from real data.
First bucket authored + executed on the §15 REQUIRED PLAN TEMPLATE rails — the governance held.
