# run19 — collapse find_hs into its 4 trade consumers + DELETE it (Comtrade; 🏁 LAST find_*)

**T1 attest:** `hs_test.py` is ISOLATED calibration (I write args) — NOT the MCP test; the MCP test is the BLIND subagent.

## What changed (mirror of run17/18, wider)
find_hs was a FREE resolver: a good/service concept → candidate LIST of HS/EBOPS codes; the CLIENT picked the code(s) +
the supply STAGE → one of 4 trade tools. Collapsed: each `codes` param on **search_trade / top_partners / top_traders /
trade_balance** takes a CONCEPT (or exact code) and resolves via **`_resolve_hs`** (mirror of `_resolve_series` over
`/v1/ext/hs/find`) — with two additions:
- **Supply-STAGE disambiguation** (the `excludes` field names the sibling stages): copper ORE→260300 vs REFINED
  copper→740311, judged by `context`.
- **4-digit family ROLL-UP** (mirrors the old client's manual `parent_code` roll-up): a 4-digit parent with ≥2 leaf
  children in the shortlist is offered as a synthetic "ALL of HS <parent>" option, so "all rice"→1006, "integrated
  circuits"→8542.
`_hs_codes_arg` (plural, mirror of `_tickers_arg`) handles the `codes` LIST. `context` added to all 4; `type`
(goods/services) threaded. find_hs DELETED; refs scrubbed.

## Resolver verified (calibration 7/7 ×2)
crude oil→270900 · copper ORE→260300 (ore) · refined copper→740311 (cathodes — STAGE) · rice→**1006** (roll-up) ·
integrated circuits→**8542** (roll-up) · tourism[services]→236 · "my favorite hobby"→no_match. `_is_hs_code`
passthrough (2709=id, 'crude oil'=concept); recall floor holds (pick ∈ candidates ∪ their parent_codes).

## 🔴 BLIND MCP test + the backend caveat
The blind subagent used the 4 trade tools with a CONCEPT in `codes` + `context` (crude oil / copper ore / rice /
semiconductors / Thai ยางพารา), **0 find_hs calls** (tool gone). But the comtrade DATA endpoint returned **500 "Server
error"** — ROOT CAUSE (traced): `comtrade.rs:74` `user_comtrade_key` needs `BYOK_ENC_SECRET` and `internal()`-errors
BEFORE the graceful `byok_missing(402)` path; the **:8090 debug backend has no `BYOK_ENC_SECRET`** (absent from .env +
process env; **prod mounts it** — deploy.sh:85). A pass-through code `2709` errors identically → the data endpoint,
which run19 does NOT touch, is the fault, NOT the collapse. Prod (with the secret) returns the graceful BYOK note or
data. So — like FRED (run17) — the RESOLVER is fully verified; the metered data leg is a :8090 config caveat.

## 🏁 Milestone
tools/list now has **ZERO find_* tools**. Every resolver has been collapsed into its consumer(s) and deleted:
find_fsconcept · find_fspattern · find_tasignal · find_oppattern · find_gics · find_megatrend · find_stock ·
find_series · find_indicator · **find_hs**. No resolver round-trips remain in the MCP.

## Diff vs run18
run18 = World Bank (verified end-to-end). run19 = the trade bucket — same template, plus supply-stage + family roll-up,
across 4 consumers with a plural `codes`. Finishing it completes the whole find_* collapse project. Next: prod deploy
(the accumulated mcp-jev + backend data.rs).
