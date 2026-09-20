# run14 — collapse find_stock into its ticker-consumers + DELETE it

**T1 attest:** re-read RESOLVER-TEST-GUIDE.md + §15 test-discipline (blind client writes own args; grade process+output
from REAL data, never self-report; mechanical tools/list; **A/B parity vs old find_stock**). Server `:8902→:8090`
(DEBUG → judge correctness not latency), Jev key from mcp-jev/.env.

## Verdict: gate [A] PASS (1 documented limitation)
- **find_stock DELETED** → absent from tools/list; a blind client cannot round-trip. **0 find_stock calls** across 10
  blind questions; every one resolved server-side and the consumer EXECUTED in one shot (or an honest reconfirm/no_match).
- Collapsed into **9 consumers** (2 more than the plan's 6 — see below): asset_pulse, stock_impact, stock_prices,
  stock_prices_batch, options_sentiment, relationships + write_note, add_to_playlist, query_notes (financials kept its
  inline walk — its reconfirm is combined with the fields axis).

## 🔴 A/B PARITY vs old find_stock (the regression ran required) — parity_test.py / parity_result.txt
Old find_stock and the new `_resolve_ticker` hit the SAME `/v1/stocks` retrieval, so the candidate set is identical →
the comparison isolates the PICK step. Over 24 queries:
- **Recall floor: 0 violations** — every NEW resolved pick ∈ OLD top_k. (ran's core ask: "ตัวใหม่ที่เลือก ต้องอยู่ใน top_k ของเดิม" ✅)
- **Boundary honesty** — junk / "the stock that will go up" → NEW no_match, where OLD returned an arbitrary rank-1 (KJL.BK).
- **The A/B CAUGHT A REAL BUG**: the first resolver instruction was company-centric (inherited from financials'
  stock-only scope) and wrongly no_match'd gold / bitcoin / US-10Y / SOFR / SPY under broad scope. Fixed → a
  **scope-aware** instruction + `__NONE__` (the acceptable asset classes derive from the consumer's scope). After the
  fix all those resolve. This is exactly why ran wanted the A/B.
- **Scope effect** (value the flat find_stock couldn't give): the same word resolves per-consumer —
  `apple` → financials/asset_pulse **AAPL.US**, broad stock_prices APPLE.COMM; `gold` → financials GOLD.US, broad GOLD.COMM.

## Per blind case
| id | question | tool (client's own) | result |
|----|----------|---------------------|--------|
| A-q1 | how is Toyota doing | asset_pulse(Toyota) | 7203.JP ✅ |
| A-q2 | price history of NVDA | stock_prices(NVDA) | NVDA.US ✅ |
| A-q3 | what moved KBANK | asset_pulse(KBANK) | KBANK.BK (Thai, exact-symbol) ✅ |
| A-q4 | compare Apple & Microsoft prices | stock_prices_batch([Apple,Microsoft]) | MSFT.US ✅ / **Apple→APPLE.COMM** ⚠️ known |
| A-q5 | how is gold doing | commodity_pulse(gold) | client chose the commodity tool ✅ |
| B-q1 | Samsung competitors | relationships(Samsung Electronics) | 005930.KO ✅ |
| B-q2 | options sentiment Tesla | options_sentiment(Tesla) | TSLA ✅ |
| B-q3 | add Nvidia/ซัมซุง/bitcoin to 'watch' | create_playlist + add_to_playlist | NVDA.US + 005930.KO + BTC-USD.CC ✅ multilingual/multi-asset |
| B-q4 | fundamentals for トヨタ | financials(トヨタ) | 7203.JP ✅ |
| B-q5 | price of my lucky stock | stock_prices(lucky stock) | no_match, honest ✅ |

## Known limitation (documented, non-blocking)
**Broad-scope bare company-word vs same-named commodity** — `stock_prices`/`stock_impact`/`stock_prices_batch` scope
includes commodities, so a bare "Apple" resolves to APPLE.COMM (the commodity), not AAPL.US. This is an INHERENT
ambiguity (apple is both a company and a commodity), NOT a regression (old find_stock rank-1 was also APPLE.COMM), and
the primary read tool `asset_pulse` (narrower scope, no commodity) resolves "Apple"→AAPL.US correctly. The mega-cap
prominence rule fixed the worse failure (a bare word mis-picking an obscure same-named FOREIGN small-cap). A future
option: reconfirm when a mega-cap company and a commodity tie on a bare word.

## New consumers found beyond the plan's 6 (C10 scrub surfaced them)
`write_note.stocks`/`mentioned_stocks`, `add_to_playlist.tickers`, `query_notes.stock` also told the client "resolve
via find_stock first" → wired through `_ticker_arg`/`_tickers_arg` (else deleting find_stock left dangling refs). Also
scrubbed the STALE `find_megatrend` refs (write_note/screen_stocks) left over from run13.

## Diff vs run13
run13 collapsed find_gics+find_megatrend (concept axis). run14 collapses find_stock (identity axis) — reusing the
already-built `_resolve_ticker` + the financials wiring pattern; the new work is per-consumer scope, the scope-aware
instruction (A/B-driven), the shared `_ticker_arg`/`_tickers_arg`, and the DELETE. tools/list now has NO
find_stock/find_gics/find_megatrend/find_fsconcept/find_fspattern/find_tasignal/find_oppattern (7 collapsed); the
remaining find_* are the 3 ext resolvers (find_hs/find_series/find_indicator).
