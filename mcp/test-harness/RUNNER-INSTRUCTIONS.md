# Blind MCP test-runner instructions

You are a BLIND MCP client running ONE test set. You know NOTHING about the server's tools in advance —
discover them from the tool list + each tool's JSON schema. NEVER guess field names from memory; read them
from the schema. Treat each `question` as a real user request.

## Transport (HOW to speak MCP — NOT a hint about which tool/args to use)
```
cd /Users/ran/Documents/marketdx/mcp/test-harness
export BEARER="avn_live_22dc8962c39593e7a5c449ff" MCP_URL="http://127.0.0.1:8901/mcp"
RUN(){ uv run --no-project --python 3.12 --with 'mcp<2',httpx python mcp_call.py "$@"; }
RUN list                  # all tools (name + summary)
RUN schema <tool>         # ONE tool's full input schema — READ field names/enums here
RUN call <tool> '<json>'  # invoke; prints JSON result
```
Be ECONOMICAL: `list` ONCE, `schema` a tool ONCE, reuse across all 10 cases. Don't re-list per case.

## For EACH case in the set file
1. Read `question` as a user would ask. Discover the right tool(s), read their schema, shape EVERY arg from
   the schema (use resolver tools if a pattern/concept/theme/gics must be resolved). Fill numbers ONLY where
   the user stated them; invent nothing.
2. Make the call(s). On error: READ the message, fix, retry once (note that you retried).
3. Judge the RESULT against that case's `acceptance` → verdict PASS / PARTIAL / FAIL (+ one-line reason).
4. Record any DEFECT: a schema/description that forced a guess, a silent/wrong result, a 500, missing data,
   a resolver-vs-executor vocabulary mismatch, a tool under-exposing an endpoint capability, a timeout, etc.
   Tag each defect's likely side: "mcp-guidance" | "fund-backend" | "ta-backend" | "data-coverage" | "harness" | "none".

## Output — write JSON to the RESULT path you are given, shape:
{
  "set": "<set name>",
  "cases": [
    { "id":"…", "question":"…",
      "tool_calls":[{"tool":"…","args":{…}}, …],   // exact args sent, in order
      "result_summary":"concise: count / top tickers / error text / what came back (NO giant dumps)",
      "verdict":"PASS|PARTIAL|FAIL", "reason":"one line",
      "defects":[{"desc":"…","side":"…"}] }
    // all 10
  ],
  "set_summary": {"pass":N,"partial":N,"fail":N,"top_defects":["…"]}
}

Keep tool_calls faithful. Keep result_summary short. After writing, reply with: result path + pass/partial/fail
tally + the 2-3 most important defects.
