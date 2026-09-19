# run09 — find_tasignal collapse into screen_unified.ta

**Code:** mdx-api `b5de0eda` · mcp-jev `3717851` (CHANGE #6 period-append) · Jev key …f2f2ec · server :8902 → mdx-api :8090 (health-checked by me before spawning).
**Set:** resolver-ta-v1 (7 cases) · 3 blind Sonnet clients, split so NL-cross (ta01) and explicit-cross (ta06) sat in different agents.

## Tally
| verdict | ids | n |
|---|---|---|
| PASS | ta01, ta02, ta03, ta04, ta05 | 5 |
| PARTIAL | ta06 (round-tripped via optional find_tasignal) | 1 |
| N/A-resolver | ta07 (client editorialized the boundary away) | 1 |

## What the blind test PROVED
- **Collapse works end-to-end, clients go direct:** 6/7 went STRAIGHT to `screen_unified.ta` with no `find_tasignal` round-trip. Nested grammar (anchor + quals, and a 2-step THEN-chain in ta05) decomposed correctly.
- **Passthrough paths (CHANGE #2/#3/#4) verified live:** numeric-range operand `40-50` (ta02) and period-suffixed tokens `sma200`/`ema50` (ta04, ta05) all passed through un-resolved and returned correct, in-band results.
- **Operand-free pattern** (squeeze, ta03) needs no invented a/b.

## What the blind test did NOT prove (honest limitation)
- **The NL-operand resolver + period-APPEND (CHANGE #6) was never exercised by the blind clients** — every Sonnet client already KNOWS the TA vocab, so they keyed everything (`crossover_up`, `sma200`, `in_range`, `squeeze_fired_up`, `near_ma`, `ema50`) and hit exact-key/token passthrough instead of sending natural language. Same "experts key by memory" effect seen for fsconcept in run06/07. A question phrased to force NL (`หุ้นที่ราคาย่อลงมาทดสอบเส้นค่าเฉลี่ย 200 วัน`, ta04) still got `b:"sma200"` typed directly.
- **The NL path IS verified — but by the plumbing smoke (my args = a health-check, not a blind test):** `screen_unified` with `a:"the 50-day moving average"` → **`ema50`** (period appended ✓); `b:"the 200-day moving average"` → honest `reconfirm` ema-vs-sma; `"breaking out of a squeeze"` → `squeeze_fired` (12 hits); `"the vibe is bullish"` → **no_match** (honest boundary). This proves CHANGE #6, but through hand-authored args, so it is NOT an MCP test of that path — it's a code-path health-check.

## Defects / follow-ups
1. **ta06 round-trip (mcp-jev-doc, minor):** a client still chose the OPTIONAL `find_tasignal` on explicit "50/200 EMA golden cross" phrasing. Same class fsconcept/fspattern showed in run07 → fixed by tightening the OPTIONAL doc steering in run08. Consider the same tightening for `find_tasignal`. Not a resolver bug; 6/7 already go direct.
2. **Server perf (server-perf):** ta02 and ta05 first-call timeouts at 120s (in_range+for_bars, and the 2-step THEN-chain over 60 bars are heavy); both succeeded on retry with a longer timeout. Correctness fine; worth a look before prod.
3. **ta07 client over-eagerness (client-behaviour):** turned a vibe into a concrete screen and presented invented criteria as the user's ask. Not our layer.

## Verdict
The `find_tasignal` collapse is **functionally correct and live**: blind clients reach `screen_unified.ta` directly and all passthrough paths return right answers. CHANGE #6 (period-append — the fix for the golden-cross "unsupported operand ema" bug) is confirmed working, but only via the health-check layer, because no blind client will send NL when it knows the keys. Remaining items are steering (ta06) + perf, both non-blocking.
