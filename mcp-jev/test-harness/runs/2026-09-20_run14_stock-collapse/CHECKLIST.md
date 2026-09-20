# CHECKLIST — collapse find_stock into its ticker-consumers + DELETE it — run14

**Governance (playbook §15):** DONE only when BOTH gates pass — **[A]** TEST via correct process (blind client +
mechanical tools/list + output-from-`matched.*` + **A/B parity vs old find_stock**) AND **[B]** every row ✅ with
concrete evidence. Plan: `fancy-wandering-nebula.md`.

## Implementation
| # | Requirement | Evidence | Status |
|---|---|---|---|
| C1 | `_ticker_arg`/`_tickers_arg` helpers (passthrough full ticker → `_resolve_ticker` → resolved/batched-reconfirm, `kind='ticker'`) | server.py:809 (`_ticker_arg`), 828 (`_tickers_arg`), 794 (`_is_full_ticker`) | ✅ |
| C2 | All consumers wired; financials kept inline (combined ticker+field reconfirm) | stock_impact 1310 · options_sentiment 1361/1369 · relationships 1465 · asset_pulse 1886 · stock_prices 2008 · stock_prices_batch 2019 · +write_note 1631 · add_to_playlist 1763 · query_notes 1685; financials inline 2515 | ✅ |
| C3 | Per-consumer SCOPE correct — verified vs live `/v1/stocks` `type` strings (stock incl .GB/.MM · etf · commodity · crypto · forex · private) | server.py:788-792 scope consts; probe: apple/gold/SOFR/bitcoin/BTC types confirmed | ✅ |
| C4 | `country` disambiguator MIRRORED (optional param → resolver) | `_TK_COUNTRY` const; params on stock_impact/relationships/asset_pulse/stock_prices; KBANK→KBANK.BK probe | ✅ |
| C5 | Dual-mode passthrough: `SYMBOL.EXCH` skips Jev; BRK.B share-class resolves | server.py:794 `_is_full_ticker`; parity: AAPL.US passthrough, resolves stay resolved | ✅ |
| C6 | Identity vs listing preserved (canonical ticker, not matched_via); GOOGL/GOOG right | server.py:742 + parity GOOGL/GOOG→GOOG.US | ✅ |
| C7 | Batch: stock_prices_batch resolves a list, ONE reconfirm, `unresolved` preserved | server.py:2019; blind B-q3 add_to_playlist 3-name batch resolved | ✅ |
| C8 | Instruction/`__NONE__` SCOPE-AWARE (broad ≠ stock-only) — **A/B caught the company-centric bug** | server.py:693 `_ticker_instr(scope)` + 713 `_ticker_none(scope)` + `_TYPE_LABEL` 685; parity: gold/bitcoin/US-10Y/SOFR now resolve | ✅ |
| C9 | find_stock DELETED from tools/list | mechanical `mcp_call list`: find_stock ABSENT; 9 consumers present | ✅ |
| C10 | Refs scrubbed — `_TICKER` string + all docstrings/instructions naming find_stock (AND stale find_megatrend from run13); `/v1/stocks` endpoints STAY | grep: 0 client-facing find_stock/find_megatrend (only internal `#` comments) | ✅ |
| C11 | `ast.parse` OK; no caller of a deleted symbol | ast OK; `_FIND_KEEP` + find_stock removed, 0 dangling | ✅ |
| C12 | mkt-cap prominence hint (prefer mega-cap company over same-named foreign small-cap) | server.py:748 `_mc()` + instruction mega-cap clause; probe: no more Fuji-apple mis-pick | ✅ |

## Test — gate [A]
| # | Test step | Evidence | Status |
|---|---|---|---|
| T1 | Re-read RESOLVER-TEST-GUIDE.md + §15 test-discipline | SUMMARY T1 attest | ✅ |
| T2 | Server :8902→:8090 + SELF health-check (NL name resolves+executes) | Toyota→7203.JP, gold→GOLD.COMM, KBANK→reconfirm/KBANK.BK probes | ✅ |
| T3 | Mechanical: tools/list NO find_stock; 9 consumers present | mcp_call list | ✅ |
| T4 🔴 | **A/B PARITY vs old find_stock** — recall floor 0 violations; boundaries→no_match (old junk); scope-aware fix (gold/bitcoin/US-10Y/SOFR resolve); scope-effect | parity_test.py + parity_result.txt | ✅ |
| T5 | Blind subagents (2×5, ≥2 consumers incl reconfirm/passthrough/boundary/batch/multilingual) → 0 find_stock / 0 round-trip | raw/agentA.json + raw/agentB.json (10/10, 0 find_stock) | ✅ |
| T6 | OUTPUT verified from REAL data (re-called agent args; right entity/listing; boundary count 0; multilingual resolve) | grades.json + re-call probes | ✅ |
| T7 | Reconfirm-in-loop — a reconfirm case surfaces candidates; agent picks + re-calls with exact ticker | A-q4 (agent re-called w/ AAPL after silent mis-resolve); boundary A/B-q5 no_match handled | ✅ (see limitation) |
| T8 | Immutable run + diff vs run13 | this dir (meta·raw⟂grades·SUMMARY·CHECKLIST·parity_test.py·parity_result.txt); SUMMARY "Diff vs run13" | ✅ |

## Gate status
- [A] TEST via correct process: ✅ — mechanical + A/B parity (recall floor 0 violations, the A/B caught+fixed the scope bug) + blind client graded from REAL data. 10/10 answered, 0 find_stock calls, 0 round-trips; 1 documented non-blocking limitation (broad-scope bare company-word vs same-named commodity — not a regression; asset_pulse correct).
- [B] All rows ✅ with evidence: ✅
- **DONE = [A] ∧ [B]:** ✅ (with the documented Apple-broad limitation noted for ran)
