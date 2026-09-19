# run11 — collapse `find_oppattern` into its consumers + DELETE it

**Code:** mdx-api `f5056c81` · mcp-jev `886de6e`+working (find_oppattern DELETED; `_resolve_oppattern` added; options_scan
+ screen_unified.options resolve NL server-side; compose expands server-side) · Jev …f2f2ec · :8902→:8090 (health-checked).
**Set:** resolver-oppattern-v1 {op01–op06} · 2 blind Sonnet clients. T1: re-read how-to-run-mcp-test.md + RESOLVER-TEST-GUIDE.md before testing (done).

## Result — 6/6 PASS (process AND output verified from real data)
| axis | proof |
|---|---|
| **Mechanical (mine)** | tools/list has **NO find_oppattern**; still has options_scan + screen_unified. |
| **Process — blind** | All 6 sent to options_scan / screen_unified — **0 find_oppattern calls, 0 round-trip** (tool gone). |
| **NL resolver genuinely exercised** | Unlike run09/10 (experts keyed TA/fund from memory), options keys are unfamiliar so clients sent NL — 'crowd getting fearful', 'cheap implied vol', 'smart money piling into calls', 'options positioning diverging from the price uptrend'. `_resolve_oppattern` did the work. |
| **Output — from `matched.*`/scan rows, not self-report** | op01 fear_building = put-skew 100th pct · op02 iv_cheap = IV 0th pct · op03 bullish = calls-heavy P/C · op04 crowded = extreme P/C · op05 compose = real 2-leg intersect (options bearish ∩ ta above-ema) · op06 unsupported = honest not_scannable, no fabrication. |

## Compose (op05) — the one nuance, handled by REUSE not a new engine
`options_scan` (single-leg) honestly returns `not_scannable` for a composite and points to screen_unified. In
screen_unified, resolving the divergence phrase → an `exec_path=compose` pattern; the server reads the
`compose_recipe` (catalog DATA), injects its ready ta `example` as a TaStep, sets the options leg + `sort='options'`,
and runs the intersect — reusing the existing ta walk + assembly. `_resolved_options` records the expansion. What
the CLIENT used to do (read recipe → build screen) is now server-side; find_oppattern is gone.

## Note on the perf numbers below (IMPORTANT)
🔴 All screen timings here were measured against **`:8090` = a `./target/debug/mdx-api` DEBUG build** (Rust debug is
10–50× slower than release). So the 16–19s figures are INFLATED debug-build artifacts, NOT real backend latency —
the same caveat retro-applies to run09/10's "ta timeout" conclusions (also measured via :8090 debug). Real
release-build perf is a SEPARATE investigation (owner: ran, separate session). The collapse correctness (6/6, both
gates) is unaffected by build type. Do not treat the numbers below as a real backend defect.

## Defect — screen slowness (measured on a DEBUG build — see note above)
- **op05 divergence is slow.** Curl direct to :8090 (no uv/MCP/Jev overhead): compose body = **19.2s**; the ta
  `above ema50` leg **ALONE = 15.9s** (the options intersect adds only ~3s). ROOT = the backend TA screen for a broad
  persistent-state signal (`above ema50`, no recency window) is ~16s — the **same root as run09/10's 120s ta
  timeouts**, not specific to compose and not introduced by the collapse (the recipe's own ta leg / old client-built
  screen are identical). Even scoped to the ~557 US-optionable names it's slow. Fix is backend-side (drive from the
  tight options leg / index the persistent-state TA scan); the MCP can't fix the backend query plan. **Raise separately.**

## Verdict
`find_oppattern` fully collapsed: options_scan + screen_unified.options resolve the behaviour (key-or-NL) server-side,
compose orchestration moved server-side, the tool is DELETED (round-trip impossible), and every output was verified
from real returned data. Same operation as fsconcept/fspattern/tasignal — no special machinery (Occam).
