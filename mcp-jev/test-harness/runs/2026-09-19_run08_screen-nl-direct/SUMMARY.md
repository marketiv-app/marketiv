# run08 — 2026-09-19 · screen_unified NL-direct (post doc-fix) — DID the ping-pong go away?

After: screen_unified concept/pattern doc = "key OR NL, server resolves — no find_* first"; find_fsconcept/find_fspattern docstrings marked OPTIONAL/escape-hatch. Server health-checked before spawn. 1 blind agent, 3 cases (sc01/sc02/sc06 from v2).

## 🎯 PRIMARY GOAL — ACHIEVED: ping-pong eliminated
| case | run07 (before) | run08 (after) |
|---|---|---|
| sc01 | find_fsconcept + find_fspattern → screen_unified | **screen_unified ONLY** (NL pattern) |
| sc02 | find_* → screen_unified | **screen_unified ONLY** (relation, NL) |
| sc06 | find_* → screen_unified | **screen_unified ONLY** (NL) |
The blind client now sends plain-English concept/pattern STRAIGHT to screen_unified — the doc fix removed the find_* round-trip the tool docs had been directing. Round-trip-reduction goal met.

## Multi-point grade
- Process: ✅ right tool, NL sent direct, no find_* hop, dual-mode passthrough works.
- Output: sc02 (total_liabilities growth_faster_than shareholders_equity → META/Samsung), sc06 (revenue accelerating → AAPL/GOOG), sc01 (gross_margin declining → XOM/ORCL) — all plausible & consistent with run07's verified data.
- Honesty: no fabrication.

## Findings (secondary)
1. **False no_match (resolver recall/gate edge):** NL "contracting for multiple years" → no_match, though `consecutive_decline` IS in the shortlist (rank 6). Root: vector recall is direction-confused — "contracting…multiple years" embeds near the GROWTH family (7/8 candidates are growth/above), decline ranks low, and Jev picks __NONE__ over the lone decline option. "declining for several consecutive years" (client's rephrase) resolves fine. → a synonym/direction recall gap; honest no_match + rephrase recovers, so not a blocker. Candidate fix: nudge _FSPATTERN_RESOLVE_INSTR to force a decline/contraction/shrink word → a decline pattern (never NONE when one is present). Hold for ≥1 more datapoint before tuning (calibration discipline).
2. **Exact-key `consecutive_decline` → Server error was TRANSIENT** — not reproducible (re-ran clean, count 8). One-off backend hiccup, not a bug.

## Verdict
Doc fix works — screen_unified fundamental leg is now genuinely COLLAPSED (client → NL → server resolves, no find_* ping-pong). One minor resolver false-negative logged for later gate tuning.
