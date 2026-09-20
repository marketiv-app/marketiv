# CHECKLIST — ticker resolver: restore language policy + add `context` — run16

**Governance (§15):** DONE = **[A]** tests pass via correct process (BLIND MCP client + calibration + recall-floor)
AND **[B]** every row ✅ with evidence. Continues run14/15 (find_stock deleted). Plan: `fancy-wandering-nebula.md`.

## Principle
find_stock worked WITHOUT Jev because its FIELD DESCRIPTION told the client: company name→native as-is; commodity/
sector concept→English. I dropped it when collapsing → native concepts drift (GOLD.COMM absent from top_k → Jev can't
recover). Restore it. + Add `context` (full sentence) so the server-side Jev disambiguates the way the client used to
when picking from find_stock's candidate list (apple fruit-vs-company).

## Implementation
| # | Requirement | Evidence | Status |
|---|---|---|---|
| C1 | Language instruction RESTORED (mirror old find_stock) in `_TICKER`: name→native · commodity/sector concept→English | server.py:185 (🌐 LANGUAGE clause) | ✅ |
| C2 | `context` param added to ALL 10 ticker consumers + threaded `_ticker_arg`/`_tickers_arg`→`_resolve_ticker` | 10 signatures carry `_TK_CONTEXT` (grep=10); calls threaded server.py:842/861/2517 + 11 consumer sites | ✅ |
| C3 | `_resolve_ticker` SPLITS: retrieval on ENTITY (q, /v1/stocks), Jev-judges on CONTEXT (fallback entity) | server.py:734 (sig) + 788-792 (`jev_q` from context) | ✅ |
| C4 | `context` field description makes the client paste the FULL user request (any language) | server.py:194 `_TK_CONTEXT` | ✅ |
| C5 | `ast.parse` OK; no ticker consumer left without `context` (uniform) | ast OK; grep=10 consumers; stock_prices schema exposes `context` | ✅ |

## Test — gate [A]
| # | Test step | Evidence | Status |
|---|---|---|---|
| T1a | CALIBRATION: apple+"ผลไม้"→APPLE.COMM · apple+"stock"→AAPL.US · apple+no-ctx→AAPL.US | context_test.py / calibration_result.txt | ✅ |
| T1b | CALIBRATION: native 茅台→600519.CG · トヨタ→7203.JP · 삼성전자→005930.KO; English gold→GOLD.COMM; compound wheat/apple | calibration_result.txt | ✅ |
| T1c | stability ×2 (14/14 both) | run1=0 run2=0 fails | ✅ |
| T2 | recall-floor (parity) — resolved pick ∈ top_k (unchanged from run15) | parity_test.py 0 violations (run15) | ✅ |
| T3 | Mechanical: tools/list NO find_stock; ticker consumers expose `context` | mcp_call list (find_stock=0) + schema stock_prices (context=1) | ✅ |
| T4 🔴 | BLIND MCP test (own args from NEW descriptions): "ขอราคาผลไม้ apple"→client passes context→**APPLE.COMM**; native 茅台→600519.CG; Thai gold→client translates→GOLD.COMM; batch compare→AAPL/MSFT. 0 find_stock | raw/agentA_context.json | ✅ |
| T5 | OUTPUT verified from REAL data (re-call agent args): apple+ผลไม้→APPLE.COMM · 茅台+หุ้น→600519.CG · apple+stock→AAPL.US | grades.json verified_from_real_data | ✅ |
| T6 | Immutable run (meta·raw⟂grades·SUMMARY·CHECKLIST·context_test.py·calibration_result.txt) + diff vs run15 | run16 dir | ✅ |

## Gate status
- [A] TEST via correct process: ✅ — BLIND subagent (own args from the NEW field descriptions) resolved the exact failing case "ขอราคาผลไม้ apple"→APPLE.COMM, native company name native, Thai commodity self-translated→GOLD.COMM, batch+context; graded from REAL data; + calibration 14/14 ×2. 0 find_stock.
- [B] All rows ✅ with evidence: ✅
- **DONE = [A] ∧ [B]:** ✅
