# run06 — 2026-09-19 · screen_unified fundamental-leg SMOKE (2 cases)

Server self-health-checked before spawn (real screen_unified tools/call → NVDA/AAPL). 1 blind agent, discipline held.

## Tally: 2 PASS / 0 / 0
- **s01** ROE>20% + revenue grew 3y → `[{roe,above,0.20},{revenue,consecutive_growth,N:3}]` → 40 rows (NVDA/GOOG/MSFT/AMZN). matched.fundamental confirms roe 0.82 (level) + revenue 3y growth. ✅
- **s02** P/E<15 + gross margin expanding → `[{pe,below,15},{gross_margin,consecutive_growth,N:3}]` → 40 rows (Tencent/Unilever/Zijin). ✅
- threshold scale correct: roe=0.20 (fraction), pe=15 (plain) — client read the schema. No needs_confirmation, no fabrication.

## Key observation (for the big set)
The blind client sent EXACT keys (roe/revenue/pe/gross_margin + above/consecutive_growth) — it knows common keys from the schema, so every operand hit the **exact-key fast-path (passthrough)**; `_resolved_fundamental` stayed empty. So this smoke proves: (a) exact-key passthrough does NOT regress, (b) screen executes correctly end-to-end. It does NOT exercise the NL→Jev path through the blind client. (NL path proven directly by grader: "return on equity"→roe, "grew every year"→consecutive_growth, "ESG score"→no_match.)

## Verdict: PASS → OK to fire the bigger set
Big set MUST include questions that FORCE NL (uncommon metric/shape the client can't key by memory — e.g. "accrued interest receivable", "construction in progress", "margin compressing multi-year", "debt rising faster than equity") so the Jev pick + reconfirm/no_match fire through the blind client.
