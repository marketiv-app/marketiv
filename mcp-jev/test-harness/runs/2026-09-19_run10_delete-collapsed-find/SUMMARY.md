# run10 — DELETE the collapsed find_* tools (enforce the collapse)

**Code:** mdx-api `b5de0eda` · mcp-jev `3717851` (untracked working copy: find_fsconcept/find_fspattern/find_tasignal DELETED + refs scrubbed) · Jev …f2f2ec · :8902→:8090 (health-checked).
**Sets:** resolver-screen-v2 {sc01,sc02,sc06} + resolver-ta-v1 {ta01,ta03,ta04} · 2 blind Sonnet clients (fundamental / technical).

## The point of this run
run09 left `find_*` registered as "OPTIONAL" and `ta06` still round-tripped through `find_tasignal`. The collapse isn't real until the tool can't be called. This run DELETES the three collapsed resolvers and proves the round-trip is now **impossible**, not just discouraged.

## Result — 6/6 PASS (process AND output both verified)
| axis | proof |
|---|---|
| **Mechanical (mine, pre-spawn)** | `tools/list` has **NO** find_fsconcept / find_fspattern / find_tasignal; **still has** screen_unified, financials, find_oppattern, find_stock, find_gics. |
| **Process — blind** | All 6 cases called **ONLY `screen_unified`** — **0 dead-tool calls, 0 round-trips**. Clients physically cannot round-trip; no resolver tool to reach for. |
| **Output — verified from `matched.*`, NOT self-reports** | I re-called each case with the agent's OWN recorded args and inspected the returned rows: sc01 gross_margin.series all-negative ×3yr · sc02 cagr_a(debt)>cagr_b(equity) every row · sc06 N=3 → genuinely count=0 (honest, not fabricated) · ta01 cross_ema50_ema200_up a>b + vol_spike dated in-window · ta03 ttm_sqz_fired_up dated in-window · ta04 near_close_sma200 strength 0.97–1.0. Every returned set genuinely satisfies its criterion. |

> ⚠️ Honesty note: the FIRST cut of grades.json graded output from the agents' answer summaries + count>0 — a self-report shortcut the test doc forbids. This table + grades.json were corrected by inspecting the real `matched.*` values (above). Verdicts held, but only after real verification.

- **Enforcement proven:** vs run09 (`ta06` round-tripped because `find_tasignal` existed), run10 has zero round-trips — deletion, not persuasion, is what closed it.
- **NL fundamental resolver genuinely exercised this time** (unlike run09's ta leg, which experts keyed): sc01 'gross margin', sc02 'total debt'/'total equity' (RELATION), sc06 'accelerating' (3 NL variants) all resolved server-side and returned correct/honest results.
- **Honest boundary:** sc06 strict 3-year acceleration → 0 results; the client reported the fallback recent-YoY list WITH a note it isn't true acceleration. Honest, not fabricated.

## Defects / follow-ups (non-blocking)
1. **server-perf:** sc01 (consecutive_decline) timed out at 120s, OK on 180s retry — same heavy-scan class as run09's ta02/ta05. Worth a look before prod.
2. **backend-semantic:** bare `accelerating` (no N) = latest-YoY, not strict multi-year; only N=3 enforces strict. Client surfaced it honestly; confirm the intended default someday.

## Caveat (same as run09, stated honestly)
Blind experts key TA vocab from memory, so the ta-leg NL resolver + period-append depth is still only health-check-verified (my args), not blind-verified. But run10's GOAL was the deletion/enforcement, and that IS blind-proven: no tool to round-trip to.

## Verdict
The three collapsed buckets (fsconcept, fspattern, tasignal) are now **fully collapsed** — resolve server-side AND the `find_` tool is gone from `tools/list`. Round-trip is impossible. Rule + rationale recorded in playbook §15 so every future bucket deletes its `find_` as part of the same unit.
