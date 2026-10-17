"""Unit test: screen_unified mode='check' / 'count' shapes (no scan, no rows) — fixtures, offline.
Run: SCREEN_SCHEMA_FILE=schema.json uv run --no-project --python 3.12 --with 'mcp<2',openai,uvicorn --with-editable ../python python test_screen_modes.py"""
import os, sys, json
assert os.environ.get("SCREEN_SCHEMA_FILE")
import server as S

fails = 0
def ok(name, cond, info=None):
    global fails
    if not cond: fails += 1; print("FAIL", name, info if info is not None else "")

class R:
    def __init__(self, d): self.d = d
    def json(self): return self.d

calls = []
def stub(validate, count=None):
    calls.clear()
    def vb(batch):
        calls.append(("validate", batch)); return validate(batch)
    def pr(path, body, timeout=8.0):
        calls.append((path, body)); return R(count(body))
    S._screen_validate_batch, S._post_retry = vb, pr

BODY = {"ta": [{"anchor": [{"pattern": "crossover_up", "a": "macd_line", "b": "macd_signal"}]}], "limit": 40, "count_total": True}
VALID = lambda b: [{"valid": True, "errors": [], "snaps": [], "notes": [], "assumed": [{"path": "window_bars", "value": 30}]}]

stub(VALID)
r = S._screen_check(dict(BODY), 10, "check", {"_resolved_ta": [{"pattern": "macd cross"}], "_resolved_scope": None})
ok("check ok", r["ok"] is True and r["mode"] == "check" and "results" not in r and "count" not in r, r)
ok("check executed_criteria = the saved form", r["executed_criteria"] == {"ta": BODY["ta"], "limit": 10}, r)
ok("check sends no limit / count_total to validate", "limit" not in calls[0][1][0] and "count_total" not in calls[0][1][0], calls)
ok("check keeps validate's assumed + resolved transparency", r.get("assumed") and r.get("_resolved_ta") and "_resolved_scope" not in r, r)
ok("check never counts or scans", [c[0] for c in calls] == ["validate"], calls)

DIV = {"code": "operand_not_for_pattern", "path": "ta[0].anchor", "message": "step 0 anchor: regular divergence is available on: [\"rsi14\",\"macd_line\"] (got 'stoch_k')",
       "allowed": {"operand": "a", "values": ["rsi14", "macd_line"]}}
stub(lambda b: [{"valid": False, "errors": [DIV]}])
r = S._screen_check({"ta": [{"anchor": [{"pattern": "divergence_bull", "a": "stoch_k"}]}]}, 10, "check", {})
ok("check failure = the run's needs_rewrite shape", r["ok"] is False and r["needs_rewrite"] and r["code"] == DIV["code"] and r["_guide"]
   and r.get("at") == "ta[0].anchor[0]" and r["nearest"][0] == {"pattern": "divergence_bull", "a": "rsi14"} and r.get("nearest_meta"), r)
ok("check failure: validated once (no second validate)", [c[0] for c in calls] == ["validate"], calls)
stub(lambda b: [{"valid": False, "errors": [{"code": "invalid", "path": "ta", "message": "something else"}]}])
r = S._screen_check({"ta": [{"anchor": [{"pattern": "x"}]}]}, 10, "check", {})
ok("an error with no guide/data still answers (not a crash)", r["ok"] is False and r["needs_rewrite"] and r["error"] == "something else", r)

stub(VALID, lambda b: {"results": [{"count": 500, "capped": True, "notes": ["n1"]}]})
r = S._screen_check(dict(BODY), 10, "count", {})
ok("count ok", r["ok"] and r["count"] == 500 and r["capped"] is True and "results" not in r and r.get("notes") == ["n1"], r)
ok("count = ONE /v1/screen/count batch, cap 500", [c[0] for c in calls] == ["validate", "/v1/screen/count"] and calls[1][1] == {"queries": [{"ta": BODY["ta"]}], "cap": 500}, calls)
stub(VALID, lambda b: {"results": [{"error": "busy"}]})
r = S._screen_check(dict(BODY), 10, "count", {})
ok("count failure says so", r["ok"] is False and r["error"] == "busy", r)
stub(lambda b: [{"valid": False, "errors": [DIV]}], lambda b: {"results": [{"count": 1}]})
r = S._screen_check({"ta": [{"anchor": [{"pattern": "divergence_bull", "a": "stoch_k"}]}]}, 10, "count", {})
ok("count on an invalid formula never counts", r["ok"] is False and r["nearest"] and all(c[0] == "validate" for c in calls), calls)

# a scope alone: a valid draft — check validates it; count does not call /v1/screen/count (it needs a condition)
SCOPE = {"universe": {"include": [{"gics": "452030", "asset_type": ["Common Stock"]}]}, "limit": 40}
stub(lambda b: [{"valid": True, "errors": []}], lambda b: {"results": [{"code": "invalid", "error": "need at least one"}]})
r = S._screen_check(dict(SCOPE), 10, "check", {})
ok("scope-only check ok", r["ok"] and r["executed_criteria"] == {"universe": SCOPE["universe"], "limit": 10}, r)
stub(lambda b: [{"valid": True, "errors": []}], lambda b: {"results": [{"code": "invalid", "error": "need at least one"}]})
r = S._screen_check(dict(SCOPE), 10, "count", {})
ok("scope-only count: ok, no count, a note, no count call", r["ok"] and r["count"] is None and r.get("note") and [c[0] for c in calls] == ["validate"], (r, calls))
# the run guard stays for run, and points drafts at mode='check'; check / count go past it
g = S.screen_unified(country="US")
ok("run without a leg still refused, mentions mode='check'", "error" in g and "mode='check'" in g["error"], g)
seen = {}
keep = S._screen_check
S._screen_check = lambda body, show, mode, resolved: seen.update(body=body, mode=mode) or {"ok": True}
try:
    for m in ("check", "count"):
        S.screen_unified(country="US", mode=m)
        ok(f"{m} with a scope alone reaches the check", seen.get("mode") == m and "universe" in seen.get("body", {}), seen)
finally:
    S._screen_check = keep

ok("mode is a declared parameter", "mode" in S.screen_unified.__annotations__)
print("PASS" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
