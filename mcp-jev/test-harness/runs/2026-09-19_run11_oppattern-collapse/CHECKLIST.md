# CHECKLIST — collapse `find_oppattern` (run11)

**Governance:** work is DONE only when **BOTH** gates pass — **[A]** the TEST passed via the correct process
(blind MCP test + mechanical tools/list + output verified from `matched.*`), AND **[B]** every row below is ✅ with
CONCRETE evidence (exact `server.py:line` or run-artifact path). Loop back and fill Evidence after each step; an
item is ✅ only when the evidence is real and checked — never "looks done". Ref: plan `fancy-wandering-nebula.md`,
playbook `resolver-replacement-design.md` §15.

## Implementation
| # | Requirement (from plan) | Evidence (file:line / artifact) | Status |
|---|---|---|---|
| C1 | `_resolve_oppattern` mirrors `_resolve_fspattern` (dual-mode: exact-key passthrough → vector→Jev→gate → `__NONE__`) | `server.py:751-798` (def); mirrors `_resolve_fspattern:560-607` | ✅ |
| C2 | `_OPPATTERN_RESOLVE_INSTR` + `_OPPATTERN_NONE_OPT` domain-specific (tense/temporal_mode aware; off-domain NONE) | `server.py:733-749` | ✅ |
| C3 | Context parity: options dict feeds dimension+temporal_mode+label+description (not one field) | `server.py:780-784` | ✅ |
| C4 | NO hardcoded vocab: exact-key check compares query to ENDPOINT candidates (`c["pattern"]`) | `server.py:770` (`cands` from `/v1/options/find-pattern:762`) | ✅ |
| C5 | `options_scan.pattern` resolves key-or-NL server-side (each CSV token); non-scan → honest guide | `server.py:1190-1207` | ✅ |
| C6 | `screen_unified.options` resolves key-or-NL, folded into batched reconfirm (kind=options) + `_resolved_options` | `server.py:2625-2668` (resolve+reconfirm); `:2774` (observability) | ✅ |
| C7 | compose(live) handled by REUSE: read `compose_recipe.legs` → inject ta example (TaStep/TaSignal) + set options+sort; no new engine | `server.py:2643-2660`; isolation-proven builds the identical screen (server log: 1× find-pattern → 3× ta/find-signal). ⚠️ see defect below | ✅ (wired) |
| C8 | compose(pending)/unsupported/supported=no → honest no_match/guide (no fabrication) | `server.py:2632-2648` | ✅ |
| C9 | `find_oppattern` tool DELETED (no `@mcp.tool ... find_oppattern`) | grep: `def find_oppattern`/`Find Option Pattern` = 0; only 4 internal `#` comments remain | ✅ |
| C10 | All client-facing refs scrubbed (options_scan desc/docstring, screen_unified options desc/docstring, cot_extremes docstring); divergence guidance relocated to screen_unified docstring | options_scan `:1216,:1228`; screen_unified options `:2495-2503`, docstring `:2555-2562`; cot_extremes `:2217,:2222`; grep 0 client-facing find_oppattern | ✅ |
| C11 | reuse `_jev_pick`/`_jev_gate`/`__NONE__` verbatim (not re-implemented); English-only | `server.py:786` (`_jev_pick`), `:790` (`_jev_gate`), `:785` (`__NONE__`); INSTR says ENGLISH | ✅ |
| C12 | syntax OK; no internal caller of the deleted tool fn | `ast.parse` OK; `grep 'find_oppattern('` minus def = 0 | ✅ |

**⚠️ Defect (C7, backend-perf, PRE-EXISTING — not a collapse bug). MEASURED (curl direct to :8090, no uv/MCP/Jev
overhead):** compose body = **19.2s**; the ta `above ema50` leg **ALONE = 15.9s** (options intersect adds only ~3s).
ROOT = the backend TA screen for a broad persistent-state signal (`above ema50`, no recency window) is ~16s — the
SAME root as run09/10's 120s ta timeouts, NOT specific to compose. The recipe's own ta leg + the old client-built
screen are identical, so the collapse introduced nothing. Even scoped to ~557 US-optionable names it's slow → the fix
is backend-side (drive from the tight options leg / index the persistent-state TA scan); MCP can't fix the query plan.

## Test — gate [A] (each row = a step with artifact evidence)
| # | Test step | Evidence (artifact) | Status |
|---|---|---|---|
| T1 | Re-read how-to-run-mcp-test.md + RESOLVER-TEST-GUIDE.md before testing | re-read in full earlier this session (before run09/10); rules applied here | ✅ |
| T2 | Restart :8902 + SELF health-check via a real tools/call | server pid 86399 LISTENING; scan-NL health-check `fear_building` count 12 | ✅ |
| T3 | Mechanical: tools/list has NO find_oppattern; HAS options_scan + screen_unified | `RUN list`: `✅ gone: find_oppattern`, `✅ present: options_scan/screen_unified` | ✅ |
| T4 | Blind subagents (own args, natural options Qs incl compose + unsupported) → 0 dead-tool / 0 round-trip | `raw/op01–op06.json`; all NL args; 0 find_oppattern calls (grep-checked) | ✅ |
| T5 | OUTPUT verified from `matched.*` (re-call agent's own args; stocks genuinely show behaviour; compose = real 2-leg intersect; unsupported = honest empty) | `grades.json` — op01 put-skew 100th pct · op02 IV 0th pct · op03/04 P/C · op05 2-leg divergence via `_resolved_options` · op06 not_scannable honest | ✅ |
| T6 | Immutable run recorded (meta · raw ⟂ grades · SUMMARY · this CHECKLIST) + diff vs run10 | `runs/2026-09-19_run11_oppattern-collapse/` complete | ✅ |

## Gate status
- [A] TEST passed via correct process: ✅ (blind + mechanical + output-from-matched; T1–T6 all ✅)
- [B] All rows ✅ with evidence: ✅ (C1–C12 + T1–T6; C7 compose ✅ wired+verified, with a flagged PRE-EXISTING backend-perf defect that is NOT a collapse bug)
- **DONE = [A] ∧ [B]:** ✅
