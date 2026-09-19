# set-04 (fundamental-expert) — MCP test report (re-graded correctly)

**Method:** blind dumb-client raw responses in `raw/set-04/`. Graded by reading the RAW `matched.fundamental` for every row (per-kind: `level`→`value`, `cohort`→`value` vs `cohort_benchmark`, `growth`→`value`+window, `relation`→`value_a`/`value_b`/`ratio`) and checking each returned row's evidence against the exact conditions the client sent. A candidate violation is READ FROM RAW and DISPROVED before it's called a defect — nothing sent outward on a guess.

## Totals — 3 axes
- **right_tool: 10/10** — screen_unified with correct multi-criteria (units, N, cohort, relation) for 9 screens; find_stock→financials for the Toyota/VW/GM compare.
- **result_correct: 10/10** — every returned row's evidence satisfies every condition (checked all rows, not a sample).
- **explanation_correct: 10/10** — narrations track the evidence.

## Per-case (rows checked vs conditions, from raw)
| id | conditions | rows | violations | verdict |
|----|-----------|------|-----------|---------|
| fe-01 | rev>$5B ∩ GM>60% ∩ op>25% ∩ net_debt/ebitda<1 | 47 | 0 | PASS |
| fe-02 | rev consec-growth N5 ∩ EPS consec-growth N5 ∩ rev>$1B | 0 | — | empty (strict double-5y; legit) |
| fe-03 | compare Toyota/VW/GM | — | — | financials digests, USD, consistent |
| fe-04 | pe below own-sector-avg ∩ roe above own-sector-avg | 41 | 0 | PASS (cohort_benchmark present, value on correct side) |
| fe-05 | revenue accelerating N2 | 60 | 0 | PASS |
| fe-06 | FCF>$500M ∩ FCF-yield>4% ∩ net income>0 ∩ cash>total_debt | 15 | 0 | PASS (relation ratio ≥1 confirmed) |
| fe-07 | gross/op/net margin each consec-growth N3 | 60 | 0 | PASS |
| fe-08 | ROIC>15% N3 ∩ D/E<0.5 ∩ current_ratio>2 (Asia) | 60 | 0 | PASS |
| fe-09 | rev>$10B ∩ R&D>$2B ∩ R&D>15%×revenue | 43 | 0 | PASS (see note) |
| fe-10 | rev CAGR>20% ∩ EPS CAGR>25% ∩ ROE>20% ∩ net_debt/ebitda<2 | 60 | 0 | PASS |

## fe-09 — a candidate that was DISPROVED (not flagged)
Two rows (PANW, BIIB) surfaced R&D `value_a` **below** the $2B line ($1.984B / $1.779B) — an apparent violation of `R&D>$2B`. Read the raw + disproved before flagging: the `rnd` matched entry surfaces the **relation's ANNUAL** operand, but the `R&D>$2B` LEVEL condition uses the **TTM** basis. One confirm/disprove DB read: PANW TTM R&D **$2.276B**, BIIB TTM R&D **$2.014B** — both > $2B → both legitimately pass. No defect.

## Findings
1. 🟢 **No defect.** (Correcting the earlier draft of this test: the "relation-form operands are null / GOOG shouldn't pass" claims were a MY-SIDE grading bug — reading `.value` instead of `.value_a` — plus a stale R&D figure. Retracted; operands surface correctly and GOOG passes at 15.16%.)
2. 🟡 **Minor evidence-completeness (not a bug):** when ONE concept carries TWO conditions with different bases (fe-09 `rnd`: a TTM `>$2B` level AND an annual `>15%×revenue` relation), the row surfaces only ONE `rnd` value (the relation's annual). A reader can't SEE the TTM value that satisfied the level leg. Optional nicety for the fund team — surface per-condition operands when a concept is used twice — but the FILTER is correct.

**Bottom line:** set-04 clean on all three axes; zero confirmed defects; the one candidate was disproved from the data, not broadcast.
