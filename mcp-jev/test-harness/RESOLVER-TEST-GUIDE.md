# Resolver MCP-test — flow, structure, traceability

Tests the Jev-backed resolvers (`_resolve_fsconcept`, `_resolve_ticker`) THROUGH the real MCP, the ONLY correct
way (see `../../mcp/test-harness/` history + Ava `docs/how-to-run-mcp-test.md`): a BLIND subagent is the MCP
client, decides tool+args ITSELF from a natural question we do NOT pre-decompose; we only supply the question
and GRADE. We will run MANY rounds — this layout makes every run immutable, versioned, and diffable.

## 🛑 The one rule (per round, no exceptions)
The client writes every `arguments` object itself (from `tools/list`+`schema`), against the REAL server
(:8902, not monkeypatched), via `mcp_call.py` (JSON-RPC — never curl `/v1/*`). We grade process+output from the
REAL answer, never a self-report. If *I* wrote an arg → it is not an MCP test. See 30-sec self-check below.

## Layout
```
test-harness/
  mcp_call.py                       # transport (JSON-RPC over the pinned SDK) — the client's ONLY wire
  serve-mcp.sh                      # server launcher (PORT=8902 BASE=<mdx-api>)
  RESOLVER-TEST-GUIDE.md            # this file
  testsets/
    resolver-ticker-v<N>.json       # IDENTITY stress (tricky names/markets/cross-listing/ambiguous/no-match)
    resolver-fsconcept-v<N>.json    # FIELD stress (whole stmt / compare / deep-dive granular / near-dup / no-match)
  runs/                             # ONE immutable dir per run — NEVER overwrite; diff dirs to compare versions
    <YYYY-MM-DD>_run<NN>_<sha7>/
      meta.json                     # version pin: date, mdx-api sha+buildtime, mcp-jev sha, jev-key suffix, sets+versions, model
      raw/<caseid>.json             # BLIND client verbatim: {question, tool_calls:[{tool,args}], answer, friction} — NO judgment
      grades.json                   # MY verdict: [{id, verdict:PASS|PARTIAL|FAIL, process, output, defects:[{desc,side}]}]
      SUMMARY.md                    # human roll-up: tally + top defects + one line per case
```

## Why this is traceable (design intent)
- **Immutable versioned runs** — never overwrite a run; re-run the SAME set after a fix → a NEW dir → `diff` the two.
- **meta.json pins the exact code** — a result is always attributable to a `git sha` + build time of mdx-api AND
  mcp-jev, plus the Jev key suffix + set versions. No "which build was this?" ambiguity.
- **Question banks are versioned + separate from runs** — same questions across runs = apples-to-apples; bump
  `-v2` only when questions change (and say why in the set's `note`).
- **raw ⟂ grades** — `raw/` is the pristine blind-client observation (args the client CHOSE + the real answer);
  `grades.json` is my judgment. Split so I can re-grade WITHOUT re-running, and raw is never contaminated by grading.
- **`lens`/`acceptance` in a set are for the GRADER only** — NEVER shown to the client (that would coach it).

## Run procedure (per round)
1. **Pick set(s) + version.** Confirm the server is the intended build: restart `serve-mcp.sh` on the code under
   test; note the mdx-api it points at (BASE).
2. **Stamp meta.** Create `runs/<date>_run<NN>_<sha7>/` and write `meta.json`:
   ```bash
   cd "/Users/ran/Documents/Ava Advisor" && MDX_SHA=$(git rev-parse --short HEAD)
   cd /Users/ran/Documents/marketdx/mcp-jev && JEV_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "n/a")
   # → meta.json: {date, mdx_api_sha, mdx_api_build_ts, mcp_jev_sha, jev_key_suffix, sets:[{name,version}], bearer_suffix, model}
   ```
3. **Spawn blind subagent(s)** — give ONLY: the transport block, and the set's `question` strings (NOT `lens`/
   `acceptance`). Each agent: `list` once → `schema` per tool once → decide args → call → for EACH case write
   `raw/<id>.json` = {question, tool_calls (verbatim args, in order, incl retries), answer, friction}. No self-grade.
4. **I grade** — read every `raw/<id>.json`, score against that case's `acceptance` (which the agent never saw):
   - **process**: right tool? args decomposed right (English translation done? country vs concept? scope)? `tools/list`
     used (no guessed params)? `{q}` vs `{key}` dual-mode respected? reconfirm handled (picked from candidates, re-called)?
   - **output**: data correct + as-of stated? right concept/ticker? near-dup picked the headline? honest at
     boundaries (no_match surfaced, not fabricated)?
   - Write `grades.json` + `SUMMARY.md`.
5. **Diff vs prior run** (same set) to see regressions/fixes across code versions.

## 🛑 30-sec self-check before typing anything into a tool call
1. Who calls the tool? → the subagent, never me.
2. Who writes `arguments`? → the client, from schema. If I typed a `concept`/`ticker`/`fields` → STOP, invalid.
3. What did the client read? → the MCP's own `tools/list`/`schema` — never my paraphrase.
4. Did I hint tool/args/"translate first"/an example? → if yes, not blind.

## Transport (given to the blind agent verbatim — mechanics only, NOT a hint)
```
cd /Users/ran/Documents/marketdx/mcp-jev/test-harness
export BEARER="avn_live_22dc8962c39593e7a5c449ff" MCP_URL="http://127.0.0.1:8902/mcp"
RUN(){ uv run --no-project --python 3.12 --with 'mcp<2',httpx python mcp_call.py "$@"; }
RUN list ; RUN schema <tool> ; RUN call <tool> '<json-args>'
```
