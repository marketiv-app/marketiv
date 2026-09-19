# CHECKLIST — collapse `find_gics` (run12)

**Governance (playbook §15):** DONE only when BOTH gates pass — **[A]** TEST via correct process (blind + mechanical
tools/list + output-from-real-data) AND **[B]** every row ✅ with concrete evidence (`server.py:line` / run artifact).
Loop back and fill Evidence after each step; ✅ only when the evidence is real and checked. Plan: `fancy-wandering-nebula.md`.

## Implementation
| # | Requirement | Evidence (file:line / artifact) | Status |
|---|---|---|---|
| C1 | `_resolve_gics` mirrors template: exact-code passthrough → `_resolve_gics_codes` shortlist → Jev → gate | `server.py:3398-3449` (passthrough `:3406`, nested-rollup `:3421`, Jev `:3434`, gate `:3436`) | ✅ |
| C2 | `_GICS_RESOLVE_INSTR` + `_GICS_NONE_OPT` domain consts (granularity-aware, off-domain NONE) | `server.py:3383-3396` | ✅ |
| C3 | Context parity: Jev options feed `[level] name` | `server.py:3431` | ✅ |
| C4 | NO hardcoded vocab: candidates from `_resolve_gics_codes`/`_gics_tax` (catalog) | `server.py:3413` (`_resolve_gics_codes`), `:3405` (`by_code`) — no literal code list | ✅ |
| C5 | `_gics_arg` helper resolves single OR CSV/list, returns (resolved, confirm, resolved_map) | `server.py:3451-3472` | ✅ |
| C6 | ALL consumers resolve key-or-NL server-side | screen_unified.gics/exclude_gics/vs_cohort.gics `:2589-2607`; brief `:1024`; write_note `:1495`; query_notes `:1556`; screen_stocks `:3056`; screen_dividends `:3144` (portfolio_context has NO gics param — study was stale) | ✅ |
| C7 | screen_unified batched reconfirm (kind=gics) + `_resolved_gics` observability | reconfirm via `_gics_arg` early-return `:2591/:2595/:2601`; `_resolved_gics` `:2801` | ✅ |
| C8 | non-resolve → honest reconfirm envelope (no fabrication) | `_gics_arg` confirm `:3466-3470`; smoke: 'my grandmother' → no_match, 'banks' nested → 4010 clean, 'retail' → soft | ✅ |
| C9 | `find_gics` tool DELETED (no `@mcp.tool ... find_gics`) | grep `Find GICS Sector`/`def find_gics` = 0; mechanical tools/list absent | ✅ |
| C10 | all client-facing refs scrubbed | `_GICS` const `:200-202`; brief `:997,:1009`; write_note `:1466,:1473`; theme_pulse `:1971`; vs_cohort `:2401`; screen_unified `:2513,:2531`; screen_stocks `:3027`; screen_dividends `:3126`. Remaining find_gics = internal `#` comments only | ✅ |
| C11 | `_resolve_gics_codes` + `_gics_*` helpers KEPT; theme_pulse still resolves gics internally | helpers untouched; smoke: `theme_pulse(q='banks')` returns concepts (T3) | ✅ |
| C12 | reuse `_jev_pick`/`_jev_gate`/`__NONE__` verbatim; English-only | `server.py:3434` (`_jev_pick`), `:3436` (`_jev_gate`), `:3433` (`__NONE__`); INSTR ENGLISH | ✅ |
| C13 | syntax OK (`ast.parse`); no internal caller of the deleted tool fn | `ast.parse` OK; `grep 'find_gics('` minus def/docstring = 0 code callers | ✅ |

## Test — gate [A]
| # | Test step | Evidence (artifact) | Status |
|---|---|---|---|
| T1 | Re-read how-to-run-mcp-test.md + RESOLVER-TEST-GUIDE.md before testing | re-read in full earlier this session; rules applied | ✅ |
| T2 | Restart :8902 + SELF health-check (NL gics screen resolves). :8090 = DEBUG build → correctness only | pid LISTENING; 'biotech'→352010 count 12 | ✅ |
| T3 | Mechanical: tools/list NO find_gics; consumers present; theme_pulse still resolves gics internally | `✅ gone: find_gics`; consumers ✅; `theme_pulse(q=banks)` returns concepts | ✅ |
| T4 | Blind subagents (own args, NL sector Qs ≥2 consumers incl ambiguous 'retail' + boundary) → 0 find_gics / 0 round-trip | raw/gi01–gi06.json; all NL gics args; 0 find_gics (grep-checked); ≥3 consumers | ✅ |
| T5 | OUTPUT verified from REAL data (universe scoped to right GICS; exclude drops banks; boundary honest) | grades.json — gi01 biotech→352010 real biotech · gi02 banks→4010 excluded · gi04 semis→4530 real semis · gi06 fintech honest | ✅ |
| T6 | Immutable run recorded (meta·raw⟂grades·SUMMARY·CHECKLIST) + diff vs run11 | run12 dir complete | ✅ |

## Gate status
- [A] TEST via correct process: ✅ (blind + mechanical + output-from-real-data; T1–T6 ✅)
- [B] All rows ✅ with evidence: ✅ (C1–C13 + T1–T6; one flagged jev-quality defect on ambiguous 'retail', NOT a mechanism bug)
- **DONE = [A] ∧ [B]:** ✅
