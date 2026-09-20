# run18 — collapse find_indicator into wb_series + DELETE it (World Bank; 2nd of the ext trio)

**T1 attest:** `indicator_test.py` is ISOLATED calibration (I write args) — NOT the MCP test; the MCP test is the BLIND
subagent (which ran END-TO-END here).

## What changed (mirror of run17)
find_indicator was a FREE resolver: structural concept → candidate LIST; the CLIENT picked the indicator id + unit
variant → wb_series. Collapsed: `wb_series` takes a structural CONCEPT (or exact id) and resolves via
**`_resolve_indicator`** (a copy of `_resolve_series`: `/v1/ext/wb/find` → fast-path exact id → options(name+unit_hint+
database) → `_jev_pick`+`__NONE__` → `_jev_gate`), **carrying the `database`** + picking the unit VARIANT from
`context`. find_indicator DELETED; refs scrubbed. `_is_indicator_id` (a `WB_WDI_…` uppercase-with-underscore code) →
passthrough; a plain concept → resolve.

## Resolver verified (calibration 8/8 ×2)
household consumption %GDP→NE_CON_PRVT_**ZS** · GDP per capita→NY_GDP_PCAP_**CD** · real per-capita→NY_GDP_PCAP_**KD**
(variant chosen from "in real terms"!) · life expectancy→SP_DYN_LE00_IN · govt debt %GDP→GC_DOD_TOTL_GD_ZS · annual
inflation→FP_CPI_TOTL_ZG (WB carries annual macro) · Nvidia stock / Apple revenue → **no_match** (true boundaries).
`database` carried; recall floor holds. (A first pass wrongly expected "US CPI"→no_match — corrected: WB genuinely has
annual CPI, so it resolves; the __NONE__ instruction was fixed to reserve NONE for true non-WB things.)

## 🔴 BLIND MCP test — END-TO-END (WB is open data / no key → /series works on :8090)
The full resolve→fetch loop FRED (run17) couldn't show locally:
- "Thailand household consumption as % of GDP, 15y" → `wb_series(q="household consumption", country="THA", context=…)`
  → WB_WDI_NE_CON_PRVT_ZS → **REAL data 53.1%→57.8% of GDP**.
- "Compare GDP per capita US/China/India" → WB_WDI_NY_GDP_PCAP_CD → **REAL multi-country ranking** (US $90k/CN $13.8k/IN $2.7k).
- "Japan life expectancy trend" → WB_WDI_SP_DYN_LE00_IN → **REAL 84.0 yrs**.
- "Nvidia revenue last quarter" → the client correctly chose **financials** (not wb_series) → NVDA.US $96.22B — the
  company boundary is handled by tool selection.
**0 find_indicator calls; context passed on every call; variant disambiguated.** Param exposed as `q` (via the `_dq`
alias family); the client used it correctly. Verified from real data (re-call → same indicator + ranking).

## Diff vs run17
Same collapse, World Bank instead of FRED. run17 verified the resolver only (FRED /series needs a key absent on :8090);
run18 verifies **END-TO-END** (WB open data). Template now proven twice → find_hs (→ search_trade/top_partners/
top_traders/trade_balance, 4 consumers) is the last find_*.
