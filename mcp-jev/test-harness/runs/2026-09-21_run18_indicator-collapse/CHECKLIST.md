# CHECKLIST — collapse find_indicator into wb_series + DELETE it — run18 (2nd of the ext trio)

**Governance (§15):** DONE = **[A]** BLIND MCP client + calibration + recall-floor AND **[B]** every row ✅ evidence.
Plan: `fancy-wandering-nebula.md`. Near-exact mirror of run17; template = `_resolve_series` (server.py:3512).

## Implementation
| # | Requirement | Evidence | Status |
|---|---|---|---|
| C1 | `_resolve_indicator(q,country,context)` mirrors the template: `/v1/ext/wb/find` → fast-path exact id → options(name+unit_hint+db) → `_jev_pick`+`__NONE__` → `_jev_gate`; carries `database` | server.py:3638 | ✅ |
| C2 | `wb_series` collapsed: `indicator` = id passthrough (`_is_indicator_id`) OR concept→resolve; `context` added; resolved `database` carried | server.py:3632 (`_is_indicator_id`) + wb_series body | ✅ |
| C3 | No hardcoded vocab — candidates ONLY from `/v1/ext/wb/find` | server.py:3644; grep clean | ✅ |
| C4 | `_INDICATOR_RESOLVE_INSTR` + `_INDICATOR_NONE_OPT` domain-specific (%GDP/US$/per-capita/constant; __NONE__=not-WB) | server.py:3617/3627 | ✅ |
| C5 | find_indicator DELETED from tools/list; refs scrubbed (module instructions, `_lim` doc) | mcp_call list; grep = internal comments only | ✅ |
| C6 | `ast.parse` OK; no caller of a deleted fn | ast OK; grep 0 dangling | ✅ |

## Test — gate [A]
| # | Test step | Evidence | Status |
|---|---|---|---|
| T1a | CALIBRATION: household consumption %GDP→NE_CON_PRVT_ZS · GDP per capita→NY_GDP_PCAP_CD · real→NY_GDP_PCAP_KD · life expectancy→SP_DYN_LE00_IN · govt debt→GC_DOD_TOTL_GD_ZS | calibration_result.txt (8/8) | ✅ |
| T1b | CALIBRATION: variant via context; annual inflation→FP_CPI_TOTL_ZG (WB has it); boundary Nvidia/Apple→no_match; `database` carried; `_is_indicator_id` passthrough | calibration_result.txt | ✅ |
| T1c | stability ×2 (8/8 both) | run1=0 run2=0 | ✅ |
| T2 | recall-floor: every resolved indicator ∈ /find top_k | indicator_test.py (in-harness) | ✅ |
| T3 | Mechanical: tools/list NO find_indicator; wb_series exposes context | mcp_call list (0) + schema (context=1) | ✅ |
| T4 🔴 | BLIND MCP test END-TO-END: concept→wb_series resolved + fetched REAL series+ranking (THA household consumption 53.1→57.8%; GDP-per-capita US/CN/IN ranking; Japan life exp 84.0); Nvidia→client chose financials. 0 find_indicator, context passed | raw/agentA_wb.json | ✅ |
| T5 | Immutable run (meta·raw⟂grades·SUMMARY·CHECKLIST·indicator_test.py·calibration_result.txt) + diff vs run17 | run18 dir | ✅ |

## Gate status
- [A] TEST via correct process: ✅ — BLIND subagent (own args) resolved every structural concept + right VARIANT and fetched REAL data END-TO-END (WB open-data works on :8090), multi-country ranking, boundary via tool selection; 0 find_indicator; + calibration 8/8 ×2 + recall-floor.
- [B] All rows ✅ with evidence: ✅
- **DONE = [A] ∧ [B]:** ✅
