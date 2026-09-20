# run16 — ticker resolver: restore find_stock LANGUAGE policy + add `context`

**T1 attest:** re-read RESOLVER-TEST-GUIDE.md + §15 + [[mcp-test-must-be-blind-client]]. `context_test.py` is an
ISOLATED calibration (I write the args) — NOT the MCP test. The MCP test is the BLIND subagent below.

## What broke + the fix (mirror the old, don't reinvent)
The failing case: "ขอราคาผลไม้ apple" (price of the FRUIT apple) → resolved to AAPL.US (the company). Two things the
find_stock collapse LOST:
1. **LANGUAGE** — find_stock's `q` FIELD DESCRIPTION told the client: *"translate a generic COMMODITY/SECTOR concept
   to English first (ทองคำ→'gold'); a COMPANY name passes as-is (茅台/トヨタ resolve)."* I dropped it when rewriting
   `_TICKER`. Proven why it matters (live /v1/stocks top-15 = the recall FLOOR): `ทองคำ`→`['oc:11664']` (Lao Bullion
   Bank), **GOLD.COMM absent** → Jev can't recover. English `gold`→GOLD.COMM present. → RESTORED the rule verbatim.
2. **DISAMBIGUATION** — old find_stock returned a candidate LIST the client picked from using its conversation context.
   Collapsed, the server had no context → it silently picked. → Added a **`context`** field (the user's full request) →
   `_resolve_ticker` now SPLITS: **retrieval on the ENTITY, Jev judges with the CONTEXT.** Uniform across all 10
   ticker consumers (shared resolver).

## 🔴 The REAL MCP test (BLIND subagent — read the NEW descriptions, wrote its own args)
| user message | client's call | result |
|---|---|---|
| "ขอราคาผลไม้ apple" (fruit) | `stock_prices(ticker="apple", context="…the fruit apple")` | **APPLE.COMM** (Fuji apple futures) ✅ — the exact case that failed today |
| "ราคาหุ้น 茅台" | `stock_prices(ticker="茅台" NATIVE, context="…stock price of 茅台/Moutai")` | **600519.CG** Kweichow Moutai ✅ |
| "ขอราคาทองคำ" (Thai gold) | client TRANSLATED the concept → `stock_prices(ticker="gold", context=…)` | **GOLD.COMM** ✅ (followed the language rule) |
| "compare Apple & Microsoft stock prices" | `stock_prices_batch(tickers=["Apple","Microsoft"], context=…)` | AAPL.US, MSFT.US ✅ |

The blind client, reading the NEW field descriptions, (a) passed the full `context` on EVERY call, and (b) applied the
language rule ITSELF — native company name as-is (茅台), commodity concept translated to English (ทองคำ→gold).
**0 find_stock calls.** Verified from real data: re-called the agent's own args → APPLE.COMM / 600519.CG / AAPL.US.

## Calibration (ISOLATED — measures the entity/context split; NOT the MCP test)
`context_test.py` 14/14 ×2 stable: apple + fruit-ctx→APPLE.COMM · apple + stock-ctx→AAPL.US · apple + no-ctx→AAPL.US
(dominant, decision a) · compound wheat/apple→WHEAT.COMM/APPLE.COMM · native names 茅台/トヨタ/삼성전자 → resolve ·
English concept gold/crude oil → GOLD.COMM/WTI.COMM · controls NVDA/Toyota.

## Multilingual confirmation (2 more BLIND subagents — raw/agentB_multilingual.json) — 12/12
Across **Thai / Chinese / Japanese / Korean / Spanish / French / German + mixed**, blind clients (own args):
- **Native company NAMES resolve** in every language: โตโยต้า→7203.JP · 苹果公司→AAPL.US · 任天堂→7974.JP ·
  삼성전자→005930.KO · 比亚迪→002594.CS · LVMH→MC.PA · SAP→SAP.XETRA. (verified from real data: 7203.JP/7974.JP/MC.PA/002594.CS)
- **Commodity CONCEPTS self-translated to English** per the language rule: 黄金→'gold'→GOLD.COMM · oro→'gold'→GOLD.COMM ·
  น้ำมันดิบ→'crude oil'→(reconfirm→WTI.COMM).
- **`context` passed on every call**; **reconfirm loop** handled (crude oil → WTI); **mixed-language batch** (比亚迪+Tesla)
  → 002594.CS, TSLA.US. **0 find_stock.**

## Diff vs run15
run15 fixed the fast-path + query-driven instruction (bare "apple" no longer the commodity, resolve-dominant). run16
restores the LANGUAGE contract (native names / English concepts) that the collapse dropped, and adds the `context`
field so the server-side Jev disambiguates with the user's full request (fruit vs company) the way find_stock's client
used to when picking from the candidate list — realized cleanly by SPLITTING retrieval (entity) from judgment (context).
