# run15 — ticker resolver: reconfirm/resolve on ambiguity (fast-path + query-driven instruction)

**T1 attest:** re-read RESOLVER-TEST-GUIDE.md + §15 + [[mcp-test-must-be-blind-client]]. 🔴 An ISOLATED harness where
I write the args (`reconfirm_test.py`/`diag`/`trace`) is a CALIBRATION harness, NOT an MCP test — the MCP test is the
BLIND subagents who write their own args. Both are below, labeled.

## What was wrong + the fix
ran flagged: bare "apple" silently resolved to APPLE.COMM (a Fuji-apple *fruit* commodity), not AAPL.US. TRACED:
- **Root cause = the FAST-PATH**, not the instruction. `_resolve_ticker`'s fast-path resolves a UNIQUE exact-symbol
  match with no Jev. APPLE.COMM's ticker symbol is literally `APPLE`, so "apple" matched it uniquely → resolved before
  Jev ran. **Fix:** guard the fast-path to an ALL-UPPERCASE single-token query (a deliberate ticker like `NVDA`/`AAPL`);
  a lowercase common word ("apple"/"gold"/"samsung") defers to Jev, which reads the word's meaning.
- **Instruction rewritten** query-driven (server.py `_ticker_instr`): the user's QUERY is the signal — a KIND word
  (stock/commodity/…) / fuller name / company-only metric / country / exact symbol → pick it; a bare word with one
  dominant everyday meaning → pick it; a genuine tie → spread → reconfirm. Removed the mis-steering hardcodes
  ("commodity-word→commodity" made "apple" read as a fruit; "mega-cap→force-pick").

## DECISION (ran) — resolve the dominant everyday reading
"99% mean Samsung Electronics / Apple the company → resolving improves UX (no round-trip); the 1% non-dominant intent
objects and corrects in conversation." So bare "samsung"→Samsung Electronics, "apple"→AAPL.US (the company), "gold"→
the commodity. RECONFIRM only when Jev is genuinely unsure — a real KIND/entity tie (SOFR: SOFR.MM vs SOFR.US vs
USSOFR.MM). The samsung trace showed Jev gives Samsung Electronics p1=1.0 (a $1.2T mega-cap dwarfing the next $73B) —
it genuinely reads Electronics as THE Samsung, like Toyota→Toyota Motor.

## 🔴 The REAL MCP test (3 BLIND subagents — they wrote their own args)
- **A (dominant, one-shot):** "Apple's stock"→AAPL.US · "gold price"→GOLD.COMM (chose commodity_pulse) · "Samsung
  financials"→005930.KO · "Toyota"→7203.JP · "Nvidia"→NVDA.US. All ONE-SHOT, **0 find_stock**, correct entities. Real
  clients naturally qualify ("Apple stock", "Samsung Electronics") + pick specialized tools.
- **B (multi-turn context):** rates conversation → EFFR→EFFR.MM, SOFR→SOFR.MM (clean); topic switch "Apple's stock"→AAPL.US.
- **C (reconfirm LOOP — the proof):** "recent price history of SOFR" → `stock_prices(SOFR)` → **RECONFIRM**
  {USSOFR.MM, SOFR.MM, SOFR.US} → the blind client PICKED SOFR.MM (the rate, matching the wording) → **RE-CALLED
  `stock_prices(SOFR.MM)`** = exact-ticker passthrough (Jev not re-run). "ticker symbol GOLD" → fast-path (uppercase) →
  GOLD.COMM, no reconfirm. → the reconfirm→client-picks→passthrough loop works end-to-end.

## Verified from REAL data (not self-report)
Re-called the agents' OWN args: asset_pulse('Apple stock')→AAPL.US · financials('Samsung Electronics')→005930.KO ·
stock_prices('SOFR')→needs_confirmation · stock_prices('SOFR.MM')→resolved (metric_kind=yield).

## Calibration (ISOLATED — NOT an MCP test; measures resolve-vs-reconfirm)
`reconfirm_test.py` 14/14 ×2 stable: apple→AAPL.US · apple-as-commodity→APPLE.COMM · apple-stock→AAPL.US · samsung→
005930.KO · Samsung Biologics→207940.KO · gold→GOLD.COMM · Toyota/microsoft/NVDA/bitcoin resolve · AAPL.US passthrough
· SOFR→reconfirm. Recall floor (parity_test.py): 0 violations; the 1 disagreement vs old rank-1 = the win (apple).

## Diff vs run14
run14 collapsed+deleted find_stock (the wiring). run15 fixes the resolver's DECISION on ambiguity: the fast-path
no longer mis-fires on lowercase common words, the instruction is query-driven, and the reconfirm loop is proven via a
blind client. The run14 "known limitation" (apple broad → commodity) is RESOLVED — apple now → the company.
