# CHECKLIST — ticker resolver: reconfirm/resolve on ambiguity — run15

**Governance (§15):** DONE = **[A]** tests pass via correct process (BLIND MCP client + calibration + real-data grade)
AND **[B]** every row ✅ with evidence. Refines run14 (find_stock already deleted). Decision (ran): resolve the
DOMINANT everyday reading (99% UX); reconfirm only a genuine tie.

## Implementation
| # | Requirement | Evidence | Status |
|---|---|---|---|
| C1 | `_ticker_instr` rewritten query-driven: signal→pick · dominant-reading→pick · genuine tie→spread→reconfirm | server.py:696 | ✅ |
| C2 | mkt-cap/name/type kept as NEUTRAL context; commodity-word + mega-cap-force hardcodes REMOVED | server.py:757 (`_mc` neutral) + 696 (no hardcodes); grep clean | ✅ |
| C3 | **Root-cause fix: fast-path guarded to ALL-UPPERCASE deliberate ticker** (lowercase common word → Jev, not a same-symbol commodity) | server.py:752 `ticker_shaped` | ✅ |
| C4 | reconfirm returns tied candidates in a client-actionable envelope (deterministic net NOT needed — instruction+fast-path sufficed) | server.py `_resolve_ticker` reconfirm branch; blind Agent C got {USSOFR.MM,SOFR.MM,SOFR.US} | ✅ |
| C5 | `_TICKER` param notes reconfirm + client resolves via context/ask + may include intent | server.py:185 | ✅ |
| C6 | `ast.parse` OK; controls still resolve (no over-reconfirm) | ast OK; calibration 14/14 ×2 | ✅ |

## Test — gate [A]
| # | Test step | Evidence | Status |
|---|---|---|---|
| T1a | signal→RESOLVE: apple stock→AAPL.US · apple-as-commodity→APPLE.COMM · Samsung Electronics→005930.KO | calibration_result.txt (14/14) | ✅ |
| T1b | bare→DOMINANT resolve (decision a): apple→AAPL.US (not the Fuji commodity) · samsung→005930.KO | calibration_result.txt | ✅ |
| T1c | controls resolve (no over-reconfirm): gold→GOLD.COMM · Toyota/microsoft/NVDA/bitcoin · AAPL.US passthrough | calibration_result.txt | ✅ |
| T1d | genuine tie → RECONFIRM: SOFR→{SOFR.MM,SOFR.US,USSOFR.MM} | calibration_result.txt | ✅ |
| T1e | stability ×2 (Jev non-deterministic) | run1=0 run2=0 fails | ✅ |
| T2 | A/B recall-floor holds: resolved pick ∈ /v1/stocks top_k | parity_test.py: 0 violations (1 disagreement = the apple WIN) | ✅ |
| T3 | Mechanical: tools/list NO find_stock; server :8902→:8090 up | mcp_call list (run14) + boot log | ✅ |
| T4a 🔴 | BLIND dominant one-shot (agent writes own args): Apple/gold/Samsung/Toyota/Nvidia resolve, 0 find_stock | raw/agentA_dominant.json | ✅ |
| T4b 🔴 | BLIND multi-turn context: rates→EFFR/SOFR clean; topic switch→Apple stock→AAPL.US | raw/agentB_multiturn.json | ✅ |
| T4c 🔴 | BLIND reconfirm LOOP: SOFR via stock_prices → reconfirm → client picks SOFR.MM → re-calls exact (passthrough) | raw/agentC_reconfirm.json | ✅ |
| T5 | OUTPUT verified from REAL data (re-call agent args): Apple stock→AAPL.US · Samsung Electronics→005930.KO · SOFR→reconfirm · SOFR.MM→yield | grades.json verified_from_real_data | ✅ |
| T6 | Immutable run (meta·raw⟂grades·SUMMARY·CHECKLIST·reconfirm_test.py·calibration_result.txt) + diff vs run14 | run15 dir | ✅ |

## Gate status
- [A] TEST via correct process: ✅ — 3 BLIND subagents (own args) covering dominant-one-shot + multi-turn context + the reconfirm→pick→passthrough LOOP; graded from REAL data; + isolated calibration (14/14 ×2) for the resolve-vs-reconfirm measurement + recall-floor. 0 find_stock calls.
- [B] All rows ✅ with evidence: ✅
- **DONE = [A] ∧ [B]:** ✅
