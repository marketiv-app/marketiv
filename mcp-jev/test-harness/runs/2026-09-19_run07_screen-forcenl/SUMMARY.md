# run07 — 2026-09-19 · screen_unified fundamental leg, BIG force-NL (8 cases)

Server self-health-checked before spawn. 2 blind agents, discipline held.

## Tally: 8 PASS / 0 / 0
- sc01 gross_margin + consecutive_decline · sc02 RELATION total_debt growth_faster_than total_equity · sc03 roe + above_average (cohort/own_sector, no invented threshold) · sc04 market_cap + compound_growth N=2 total_change=1.0 · sc05 net_income + turned_positive · sc06 revenue + accelerating (near-dup vs consecutive_growth) · sc07 ESG → no_match (honest) · sc08 rnd_to_revenue above 0.15 + gics45 + US.
- Exercised: NL metric, NL shape, RELATION form, COHORT, COMPOUND params, near-dup, no_match. All correct, no fabrication, no false reconfirm.

## Observation (same as run06 / financials r1)
The blind client still tends to send resolved KEYS (it translates อัตรากำไรขั้นต้น→gross_margin itself, or calls find_fsconcept first), so screen_unified's self-resolve mostly hits the exact-key fast-path. Its real value = (a) no-regression safety, (b) catching genuine NL / obscure / typo terms, (c) the reconfirm/no_match gate (sc07 ESG fired). The RESOLVERS produce correct keys/shapes whether called standalone or via self-resolve — the full chain is validated.

## Defect (separate bucket — NOT the fundamental resolver)
- **find_gics broken on mcp-jev**: returns tool error "Missing credentials … OPENAI_API_KEY". The gics resolver is OpenAI/deepseek-based (NOT yet migrated to Jev) and its key isn't set in mcp-jev's env. Agent worked around with the schema's example prefix `gics='45'`. → resolves when we (a) migrate gics to Jev [roadmap], or (b) set OPENAI_API_KEY on mcp-jev. Logged, not fixed here.

## Verdict
fundamental leg (fsconcept + fspattern, incl relation/cohort/compound) = VALIDATED through blind client. fspattern bucket = closed-loop tested. Next: ta (find_tasignal) / options / gics buckets, or deploy.
