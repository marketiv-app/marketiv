# CHECKLIST — collapse find_series into fred_series + DELETE it — run17 (PILOT for the ext trio)

**Governance (§15):** DONE = **[A]** BLIND MCP client + calibration + recall-floor AND **[B]** every row ✅ evidence.
Plan: `fancy-wandering-nebula.md`. Template = `_resolve_fspattern` (server.py:893). Reuse `_jev_pick`/`_jev_gate`/
`__NONE__`; retrieval reuses `/v1/ext/fred/find`.

## Implementation
| # | Requirement | Evidence | Status |
|---|---|---|---|
| C1 | `_resolve_series(q,country,context)` mirrors the template (retrieval `/v1/ext/fred/find` → fast-path exact id → options(context parity) → `_jev_pick`+`__NONE__` → `_jev_gate`; carries `transform`) | server.py:3512 | ✅ |
| C2 | `fred_series` collapsed: concept→resolve (id via `_is_series_id` passthrough); `context`+`country` added; resolved suggested_transform = default (client overrides) | server.py:3563 (`_is_series_id`) + 3571 (fred_series body) | ✅ |
| C3 | No hardcoded vocab — candidates ONLY from `/v1/ext/fred/find` | server.py:3531; grep clean | ✅ |
| C4 | `_SERIES_RESOLVE_INSTR` + `_SERIES_NONE_OPT` domain-specific (headline/core, SA/NSA, PCE/CPI; __NONE__=not-a-FRED-series) | server.py:3497/3506 | ✅ |
| C5 | find_series DELETED from tools/list; refs scrubbed (fred_series doc, WB comment, macro_pulse, module instructions) | mcp_call list (find_series=0); grep = internal comments only | ✅ |
| C6 | `ast.parse` OK; no caller of a deleted fn | ast OK; grep 0 dangling | ✅ |

## Test — gate [A]
| # | Test step | Evidence | Status |
|---|---|---|---|
| T1a | CALIBRATION: inflation→CPIAUCSL(pc1) · core PCE→PCEPILFE · core inflation→CPILFESL · unemployment→UNRATE(lin) · 10y→DGS10 · fed funds→FEDFUNDS | series_test.py / calibration_result.txt (7/7) | ✅ |
| T1b | CALIBRATION: boundary "ISM manufacturing PMI"→no_match; transform carried; `_is_series_id` passthrough correct | calibration_result.txt | ✅ |
| T1c | stability ×2 (7/7 both) | run1=0 run2=0 | ✅ |
| T2 | recall-floor: every resolved series_id ∈ /find top_k | series_test.py (in-harness check) | ✅ |
| T3 | Mechanical: tools/list NO find_series; fred_series exposes context+country | mcp_call list (0) + schema (context+country=2) | ✅ |
| T4 🔴 | BLIND MCP test (own args): concept + context → right series_id+transform (CPIAUCSL/CPILFESL/UNRATE), JP via country, ISM→no_match. 0 find_series calls | raw/agentA_macro.json | ✅ |
| T5 | Immutable run (meta·raw⟂grades·SUMMARY·CHECKLIST·series_test.py·calibration_result.txt) + diff vs run16 | run17 dir | ✅ |

## Gate status
- [A] TEST via correct process: ✅ (resolver collapse) — BLIND subagent (own args from schema) resolved every macro concept to the right series_id + transform (core-vs-headline disambiguated), ISM→honest no_match, 0 find_series; + calibration 7/7 ×2 + recall-floor. 🔴 The DATA-FETCH `/v1/ext/fred/series` returns "Server error" on :8090 — a PRE-EXISTING backend-config issue (a direct exact-id call errors too; unchanged by run17), documented in grades.json/SUMMARY, not a collapse defect.
- [B] All rows ✅ with evidence: ✅
- **DONE = [A] ∧ [B]:** ✅ (with the :8090 fred-data-endpoint backend caveat noted)
