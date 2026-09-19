# run03 — 2026-09-19 · fix run01 defect #2/#3 (phantom statement columns)

**Fixes** run01 defects #2 (stale [income] periods = actually annual-vs-quarterly, NOT a bug) and #3 (legacy
empty year columns 2002-2007 in whole-statement tables).

## Root cause (traced)
`dividend_per_share` is stored in `fund_facts` under a `statement` tag but keyed by **dividend ex/pay dates**
(period_end = 2007-11-13, 2026-08-20, …), NOT fiscal period-ends. `statements_payload` reads every fund_facts row
and builds statement columns per `period_end` → each old dividend date becomes a phantom 1-line "period" column in
the whole-statement view. (Independent of the catalog cashflow→income move: the pollution is the DATE, not the tag.)

## Fix (financials_db.rs) — SCOPED to the statement view only
`NON_STATEMENT_LINES = ["dividend_per_share"]` + `strip_non_statement_lines(&mut st)` applied ONLY when emitting the
whole-statement block (digest_from_db statements_mode + fields_from_db statement/all branches). NOT touched:
`statements_payload` (shared builder) and the specific-fields branch → a direct `fields=dividend_per_share` still
returns DPS, and the digest keeps dividend_yield/payout/cagr.

## Verified (MSFT.US)
- whole cashflow periods → `2026/2025/2024/2023/2022-06-30` ONLY (fiscal year-ends); phantom 2002-2007 dates GONE; `dividend_per_share in cashflow = false`.
- `fields=dividend_per_share` → still returns the series [2.73, 3.40, 3.08…] (dividend-dated, the correct DPS shape).
- digest → dividend_yield 0.74% / payout 19.8% / cagr 10.2% intact.

## Note
Defect #1 (income annual line-items vs digest quarterly as_of) was NOT a bug — annual statement's latest COMPLETE
year (FY2025 Sep) legitimately differs from the digest's latest QUARTER (2026-06). No change needed.
