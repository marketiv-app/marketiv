# Memo → Fund team — `financials` tool returns ONLY the latest value for valuation ratios (pe/pb/ev_ebitda), ignoring `period` — and MISLABELS a past-year request

**From:** TA/MCP team · **Date:** 2026-08-26 · **Found via:** blind dumb-client test of set-07 (valuation-value persona), case **vv-07** ("Is Nestlé cheap vs its own history?"). **This one is CONFIRMED** — reproduced by direct MCP calls + verified the data exists in the backend. (Unlike the earlier relation-form false alarm, I read the raw and disproved the alternatives before writing this.)

## 1. Symptom
`financials` accepts a `period` selector (schema: `'5'/'5y'` = last 5 years, `'2023'` = that fiscal year, history reaches ~4–5y back). It works for statement line-items but is **silently ignored for valuation ratios**.

Reproduced on the deployed MCP (NESN.SW):
```
financials {tickers:[NESN.SW], period:"5y", fields:"pe"}
  → "period: last 5 years" ... pe: latest=27      ← header says 5y, body is ONE latest value

financials {tickers:[NESN.SW], period:"2023", fields:"pe"}
  → "period: fiscal year(s) 2023" ... pe: latest=27   ← asks 2023, RETURNS TODAY'S pe LABELED 2023
```
Same for `pb` (period:2023 → `pb: latest=6.97`) and `ev_ebitda` (period:2022 → `ev_ebitda: latest=16`). The whole valuation family behaves identically.

## 2. Two problems, one of them a correctness bug
- **(a) No history (missing feature).** "Cheap vs its own history" — the core valuation-investor question — is unanswerable via this tool. It can only ever say "pe = 27 now," never "27 vs its own 5-year range."
- **(b) MISLABELED past-year value (correctness bug).** Asking `period:"2023", fields:"pe"` returns the CURRENT pe (27) under a **"fiscal year(s) 2023"** header. A client that trusts the label will report today's multiple as the 2023 multiple — a silent wrong answer, not just a missing one.

## 3. It's a wiring gap, NOT a data gap — disproved the alternatives
- **`period` works generally** — same tool, same NESN, `fields:"revenue", period:"5y"` returns a real series: `2025=89.89B, 2024=91.72B, 2023=93.35B, 2022=94.78B`. So it's not the tool/period mechanism; it's valuation-ratios specifically that ignore it.
- **The history EXISTS in the backend** — `fund_valuation_series` has NESN **208 weekly points, 2023-01 → 2026-08**, for pe/pb/ev_ebitda (pe latest 27.4 vs early-2023 ~28.4; pb 7.0 vs 6.2; ev_ebitda 16.2 vs 19.2). The data is right there — the `financials` endpoint just doesn't read the series for these metrics.

## 4. Asks
1. **Serve the valuation-ratio history** — when `period` requests a range/multiple years and `fields` includes pe/pb/ev_ebitda (or the digest), read `fund_valuation_series` (weekly, basis 'W') and return the series like line-items do, so "cheap vs own history" works.
2. **Fix the mislabel (do this even if #1 is deferred)** — if only the latest value is available for a valuation ratio, do NOT stamp it with the requested past-year header. Either return the actual as-of date, or say "latest only — no per-period valuation series" — never emit `latest=27` under "fiscal year(s) 2023".

## 5. Not a client problem
The dumb client handled vv-07 correctly — it reported the current multiple and explicitly said "I could NOT pull a clean multi-year history of Nestlé's OWN P/E," rather than fabricating a range. The gap is entirely on the tool surface.

## 6. Repro (dumb-client, not curl)
```
financials {tickers:["NESN.SW"], period:"5y", fields:"pe"}        # expect series; get latest only
financials {tickers:["NESN.SW"], period:"2023", fields:"pe"}      # expect 2023 pe; get latest LABELED 2023
financials {tickers:["NESN.SW"], period:"5y", fields:"revenue"}   # control: correctly returns a 4-year series
```
Ping us and we'll re-run the blind harness once valuation-ratio history is served / the label is fixed.


---

# ✅ RESOLVED (verified 2026-08-26) — fund team shipped the fix; blind re-test passes.
- `financials(NESN.SW, period:5y, fields:pe)` now returns a per-fiscal-year SERIES: `2025-12=19  2024-12=16  2023-12=24`.
- `financials(NESN.SW, period:2023, fields:pe)` now returns `pe: 2023-12=24` (the real 2023 value) — the mislabel-as-latest bug is GONE. pb/ev_ebitda fixed likewise.
- Blind re-test vv-07: client correctly answered "current 27.4x vs 16–24x own history → NOT cheap vs itself." Closed.
