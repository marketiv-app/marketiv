# Memo → Fund team — PEG has no first-class surface; the AND-decompose is a fine POC workaround, but there's a nicer answer (both operands are already returned)

**From:** TA/MCP team · **Date:** 2026-08-26 · **Found via:** blind dumb-client test of set-07 (valuation-value), case **vv-09** ("PEG < 1 in the US — cheap relative to GROWTH, not just low P/E"). **This is an ENHANCEMENT, not a defect** — nothing is wrong; the current behavior is honest and the client answered well. Flagging a cleaner path.

## 1. What the client did (and it was smart)
There is no native PEG metric/pattern. `find_fsconcept("PEG")` didn't resolve one, so the blind client **decomposed** PEG into its two parts and AND-screened them: `pe low` **AND** `net_income consecutive_growth_sharp N=3` (positive, meaningful growth). Honest, and it correctly avoided the negative-earnings PEG blow-up. Good enough for a POC.

## 2. Why it's only a proxy (the limitation worth knowing)
PEG is a **ratio** (P/E ÷ earnings-growth%), and the value of a PEG screen is *ranking by that ratio*. An AND of "low P/E" + "high growth" is not the same:
- A name with **P/E 22 & 45% growth** (PEG ≈ 0.49 — excellent) can be **dropped** by the "low P/E" leg, while
- a name with **P/E 9 & 10% growth** (PEG ≈ 0.90 — worse) passes.
So the AND-screen can exclude the best PEG names and rank by neither operand's ratio. The client can't say "here are the 20 lowest-PEG names" or "PEG = 0.6 for this one."

## 3. The nicer answer — both operands are ALREADY in the response
A `screen_unified` fundamental screen already returns, per row in `matched.fundamental`:
- `pe` as a **level** value, and
- earnings growth as a **growth** value (e.g. `eps_diluted` 3y CAGR → `{kind:"growth", value:0.42, window:"3y_cagr"}`).

Two levels of fix, pick per appetite:
1. **Cheap / interim (no new metric type):** when a screen contains both a `pe` condition and an eps-growth condition, also emit a computed **`peg`** per row = `pe.value / (growth.value*100)` (guard growth>0), and let the client sort/threshold by it. The client then delivers the real "PEG = 0.6, ranked lowest-first" answer using data you already compute — no new subsystem.
2. **First-class (nicer, more work):** expose `peg` as a real screenable metric / a `relation` (pe higher_than growth×k), so `peg below 1` is a single condition the executor ranks on. The real blocker here is that **earnings growth is only expressible as a PATTERN today, never as a comparable LEVEL metric** — so a ratio between a level (pe) and a growth-rate can't be formed in one condition. Making growth-rate available as a level metric would unlock PEG *and* any other "value-vs-growth" ratio cleanly.

## 4. Ask
Not urgent. If/when convenient: **option (1)** — surface a computed `peg` per row whenever pe + an eps-growth condition co-occur — gives the value persona the actual ratio for near-zero cost, and turns vv-09 from "smart proxy" into a direct answer. Option (2) is the real fix but needs growth-as-level first.

## 5. Repro
```
find_fsconcept {q:"PEG price earnings to growth ratio"}   # returns no PEG concept
screen_unified {fundamental:[{concept:"pe",pattern:"low"},
                             {concept:"net_income",pattern:"consecutive_growth_sharp",N:3}], country:["US"]}
# rows carry pe (level) + growth (value) separately — today the client must eyeball, can't rank by PEG
```


---

# ✅ RESOLVED (verified 2026-08-26) — fund team shipped the fix; blind re-test passes.
- Fund team took the "real fix" (option 2): growth is now a first-class LEVEL metric (`eps_diluted_growth`, `net_income_growth`, `revenue_growth`, `ebitda_growth`, curated). PEG<1 is now expressible as a relation: `pe lower_than eps_diluted_growth ×1` → the response `ratio` field IS the PEG (NVDA 0.23, GOOG 0.93, META 0.72). Blind re-test vv-09: 60 US rows, all PEG<1, ranked. Closed.
- ⚠️ FOLLOW-UP (minor): the new growth-level metrics are stored in PERCENT (eps_diluted_growth NVDA = 204.24), but the schema's relation-`multiple` convention note says "bounds are FRACTIONS (0.15=15%)." A blind client first tried `multiple:100` before correcting to `multiple:1`. Consider a per-metric unit hint so the relation multiple isn't ambiguous for percent-valued growth metrics.
