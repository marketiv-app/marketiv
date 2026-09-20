# run17 — collapse find_series into fred_series + DELETE it (PILOT for the ext trio)

**T1 attest:** re-read RESOLVER-TEST-GUIDE.md + §15 + [[mcp-test-must-be-blind-client]]. `series_test.py` is an
ISOLATED calibration (I write args) — NOT the MCP test. The MCP test is the BLIND subagent.

## What changed (same operation as fspattern/gics)
find_series was a FREE resolver: macro concept → candidate LIST; the CLIENT picked series_id + transform → fred_series.
Collapsed: `fred_series` takes a macro CONCEPT (or an exact id) and resolves server-side via **`_resolve_series`**
(mirror of `_resolve_fspattern`: `/v1/ext/fred/find` → fast-path exact id → options(title+units+SA+→transform) →
`_jev_pick`+`__NONE__` → `_jev_gate`), **carrying the suggested transform** as the default. Added `context` (run16 —
the user's full request, to pick the VARIANT) + `country`. find_series DELETED; refs scrubbed.

## Resolver verified (calibration 7/7 ×2 + blind)
inflation→CPIAUCSL/pc1 · core PCE→PCEPILFE · **core inflation→CPILFESL (headline vs core!)** · unemployment rate→
UNRATE/lin · 10y yield→DGS10 · fed funds→FEDFUNDS · ISM manufacturing PMI→**no_match** (honest boundary). `_is_series_id`
passthrough: CPIAUCSL/DGS10 = id (skip Jev); GDP/CPI/"core PCE" = concept → resolve. Recall floor: every resolved
series_id ∈ the /find top_k.

## 🔴 BLIND MCP test (subagent, own args from the schema)
`fred_series(q=<concept>, context=…, country?)` — the param is exposed as `q` (the `_dq` alias family q/query/concept);
the client used it correctly. m1 "US inflation"→CPIAUCSL/pc1 · m2 "core inflation"→CPILFESL · m3 "unemployment rate"→
UNRATE/lin · m4 "US vs Japan inflation"→CPIAUCSL + country=JP · m5 "ISM PMI"→no_match. **0 find_series calls.**

## 🔴 KNOWN backend caveat (NOT run17)
`/v1/ext/fred/series` (the DATA-FETCH, downstream of the resolver) returns bare **"Server error"** on the **:8090 DEBUG
backend** for every series_id — including a **direct exact-id call with no resolution**. fred_series's
`_ext('/v1/ext/fred/series', …)` is UNCHANGED by run17 → this is a pre-existing :8090 backend/config issue (the FRED
data source not configured/reachable in the debug build), not the collapse. The RESOLVER step (`/v1/ext/fred/find`)
works. On a backend where /series works, the collapse delivers resolve + fetch in one call.

## Diff vs run16
run16 = the ticker context/language fix. run17 = the FIRST ext-resolver collapse (find_series → fred_series), reusing
the fspattern template + the run16 `context` split (retrieval on the concept, Jev judges with context) to pick the
right variant/transform. Template now proven → find_indicator (→wb_series) + find_hs (→4 trade tools) reuse it next.
tools/list find_* remaining: find_indicator, find_hs.
