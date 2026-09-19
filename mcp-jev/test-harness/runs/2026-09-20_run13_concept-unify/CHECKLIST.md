# CHECKLIST — UNIFIED concept resolver (kills find_gics + find_megatrend + deepseek/gazetteer) — run13

**Governance (playbook §15):** DONE only when BOTH gates pass — **[A]** TEST via correct process (blind client +
mechanical tools/list + output-from-real-data) AND **[B]** every row ✅ with concrete evidence (`server.py:line` /
run artifact). Plan: `fancy-wandering-nebula.md`.

## 🔴 Scope correction (ran, mid-run) — a FULL collapse in ONE run, not a phased deferral
I first tried to DEFER deleting find_megatrend + the deepseek gics machinery to "P2" ("other consumers still call it,
can't delete yet"). ran corrected this bluntly: **this is a NEW MCP — nobody external calls these tools**
("ช่างแม่ง function อื่น … นี่ของใหม่ ไม่มีใครเรียกใช้"), and the POINT of Jev is to **replace** the deepseek/gazetteer
resolver. So the right move was to **rewire EVERY consumer to the unified resolver and DELETE the deepseek resolver
wholesale, in this run** — not preserve the old machinery out of fear of breaking sibling tools.
- **Rewired** (all now via `_resolve_concept`/`_scope_resolve`/`_theme_node(s)`): screen_unified, brief, write_note,
  query_notes, screen_stocks, screen_dividends, theme_summary, theme_players, private_movers, theme_pulse, suggest_cta.
- **Deleted**: `resolve_themes` (=find_megatrend tool) + `_to_node`/`_to_nodes`/`_gazetteer`/`_match`/`_solve`/
  `_children`/`_ALIAS`; and the whole gics deepseek block `_gics_arg`/`_resolve_gics`/`_resolve_gics_codes`/`_gics_gaz`/
  `_gics_match`/`_gics_solve`/`_gics_rollup`/`_gics_out`/`_gics_tax`/`_GICS_ALIAS`/`_GICS_MULTI`/`_normalize_gaz_query`.
- **Kept** `_taxonomy`+`_node_out` (theme_pulse uses them to echo node NAMES — not resolvers). Kept `_deepseek` for its
  two NON-resolver features only: the ETF pick in theme_pulse + CTA curation in suggest_cta. No concept→code resolution
  uses deepseek anymore.

## Implementation
| # | Requirement | Evidence | Status |
|---|---|---|---|
| C1 | Noul primitive `_jev_noul`/`_jev_nouls` (N nouls, ONE TypeSafe call, `type:"noul"`) | server.py:406,384 | ✅ |
| C2 | `_resolve_concept`: cache → search_concepts (both taxonomies) → `_jev_nouls` → theme-priority-guard → typed refs | server.py:423→434→436→462→458-508 | ✅ |
| C3 | Context parity: Noul framing feeds name(+embedded description) | server.py:441 `_ctx` in theme(449)+gics(456) prompts; backend data.rs search_concepts returns `text` | ✅ |
| C4 | NO gazetteer / NO deepseek in the resolve path (candidates only from search_concepts) | server.py:436 sole source; grep = 0 deepseek/gazetteer in resolver | ✅ |
| C5 | Every consumer takes NL concept → server routes typed ref by axis (gics→gics leg, theme→megatrend/theme leg); raw code/id passthrough | screen_unified 2779-2801, brief, write_note, query_notes, screen_stocks, screen_dividends + theme tools via `_theme_node(s)`; wire_test.py all pass | ✅ |
| C6 | Forward-flow: resolved ref → tool EXECUTES → results in one shot; only gated reconfirm returns | live: theme_summary('semiconductors')→real summary; screen_stocks('AI')→3 stocks; theme_pulse('banks')→gics 4010 executed | ✅ |
| C7 | Multi-label ("retail"→[2550,301010]) + compound CSV/list | live resolver: banks→[4010,40203010], retail→[2550,301010]; wire_test compound/list pass | ✅ |
| C8 | Axis decision right (semis/AI→theme, banks/airlines/tobacco→gics, boundary→no_match) | live probes: semiconductors/AI→theme, banks/retail/luxury→gics, "my favorite stocks"→no_match | ✅ |
| C9 | find_megatrend + find_gics ABSENT from tools/list | `mcp_call.py list` (post-delete): neither present; consumers all present | ✅ |
| C10 | deepseek/gazetteer resolver machinery DELETED + refs scrubbed | grep = 0 code/comment refs to any deleted symbol; only `_deepseek` ETF(2095)+CTA(3579) remain | ✅ |
| C11 | single-axis honesty: gics-only screen_dividends refuses a THEME concept with an honest note | live: screen_dividends(gics='semiconductors') → `not_a_sector` guide (→ use screen_unified) | ✅ |
| C12 | result cache checked before Nouls | server.py:417 `_concept_cache` + 423-432 lookup; in-process (embed already cached backend-side — comment) | ✅ |
| C13 | reuse `_jev_gate` + search_concepts + query-embed cache; English-only | server.py:369,436; tool contract 🔴 ENGLISH (2688) | ✅ |
| C14 | `ast.parse` OK; no caller of a deleted fn | ast OK (final); grep 0 dangling | ✅ |

## Test — gate [A]
| # | Test step | Evidence | Status |
|---|---|---|---|
| T1 | Re-read RESOLVER-TEST-GUIDE.md before testing | SUMMARY.md T1 attest | ✅ |
| T2 | Server up :8902→:8090 (Jev key from .env) + SELF health-check | boot log + 5 live tool calls all resolved+executed | ✅ |
| T3 | Mechanical: tools/list NO find_gics/find_megatrend; consumers present | `mcp_call.py list` post-delete (C9) | ✅ |
| T4 | Blind subagents (own args, NL concepts across ≥2 consumers incl compound + boundary) → 0 deleted-tool / 0 round-trip | raw/agentA.json + raw/agentB.json: 10/10, 0 deleted-tool calls, 0 resolver round-trips | ✅ |
| T5 | OUTPUT verified from REAL data (axis right; theme members; gics cohort; honest boundary) | grades.json: retail→Walmart/Costco (301010)+Amazon (2550); banks∪insurance→4010/40203010/4030/35102030; C11 refusal | ✅ |
| T6 | Immutable run recorded (meta·raw⟂grades·SUMMARY·CHECKLIST) + diff vs run12 | this dir complete; SUMMARY "Diff vs run12" | ✅ |

## Gate status
- [A] TEST via correct process: ✅ — mechanical (T3) + blind subagent client (T4) with output graded from REAL returned data (T5); 10/10 PASS, 0 deleted-tool calls, 0 resolver round-trips.
- [B] All rows ✅ with evidence: ✅ — all C-rows ✅ with concrete evidence.
- **DONE = [A] ∧ [B]:** ✅
