"""Unit test: screen_unified takes the SAVED formula shape verbatim (`criteria`) and refuses unknown top-level args.
Offline: SCREEN_SCHEMA_FILE=<saved schema>; /v1/screen + validate stubbed.
Run: SCREEN_SCHEMA_FILE=schema.json uv run --no-project --python 3.12 --with 'mcp<2',openai,uvicorn --with-editable ../python python test_criteria.py"""
import os, sys, json
assert os.environ.get("SCREEN_SCHEMA_FILE")
import server as S

fails = 0
def ok(name, cond, info=None):
    global fails
    if not cond: fails += 1; print("FAIL", name, info if info is not None else "")

sent = []
class Resp:
    status_code = 200
    def __init__(self, d): self.d = d
    def json(self): return self.d
class Client:
    def post(self, path, json=None, timeout=None):
        sent.append((path, json)); return Resp({"results": [], "count": 0})
class H: _client = Client()
class M: _http = H()
S.mdx = lambda: M()
S._screen_validate_batch = lambda batch: [{"valid": True, "errors": []} for _ in batch]
S._check = lambda r: None
S._resolve_fund_conds = lambda conds, resolved, pending: None   # keys pass through (resolution is covered live)
S._resolve_ta_steps = lambda steps, resolved, pending: None
S._resolve_oppattern = lambda q: {"status": "resolved", "pattern": q, "query": q}

args = dict(country=["US"], size=["large"], theme=[12000000], exclude_country=["CN"], min_market_cap_usd=1e9,
            ta=[S.TaStep.model_validate({"anchor": [{"pattern": "crossover_up", "a": "macd_line", "b": "macd_signal"}],
                                         "quals": [{"any": [{"pattern": "above", "a": "close", "b": "ema200"}], "within": 0}]})],
            fundamental=[S.ScreenCondition.model_validate({"concept": "roe", "pattern": "above", "threshold": 0.15})],
            options="fear_building", options_horizon="short", timeframe=2, window_bars=40, dividend_min_streak_years=5, limit=7)
run = S.screen_unified(**args)
first = sent[-1][1]
ec = run.get("executed_criteria")
ok("run returns executed_criteria", ec and ec.get("ta") and ec.get("fundamental") and ec.get("options"), run)
chk = S.screen_unified(criteria=json.loads(json.dumps(ec)), mode="check")
ok("check with criteria=executed_criteria → the same executed_criteria", chk.get("ok") and chk["executed_criteria"] == ec, (ec, chk))
run2 = S.screen_unified(criteria=json.loads(json.dumps(ec)))
ok("run with criteria → the same request + executed_criteria", run2.get("executed_criteria") == ec and sent[-1][1] == first, (first, sent[-1][1]))
cnt = S.screen_unified(criteria=ec, mode="count")
ok("count with criteria works", cnt.get("ok") is not None, cnt)
# a change applied inside criteria is honoured
ec2 = json.loads(json.dumps(ec)); ec2["fundamental"][0]["params"]["threshold"] = 0.2
ok("a change inside criteria is used", S.screen_unified(criteria=ec2, mode="check")["executed_criteria"]["fundamental"][0]["params"]["threshold"] == 0.2)
# mixing / bad shapes
r = S.screen_unified(criteria=ec, country=["TH"])
ok("criteria + a formula field → error", "error" in r and "country" in r["error"], r)
ok("criteria + sort/limit is fine", S.screen_unified(criteria=ec, limit=3, mode="check")["executed_criteria"]["limit"] == 3)
ok("criteria with an unknown field → error", "technical" in S.screen_unified(criteria={"technical": "rsi < 30"}).get("error", ""))
ok("criteria with two include groups → error", "ONE group" in S.screen_unified(criteria={"universe": {"include": [{"country": ["US"]}, {"country": ["TH"]}]}, "ta": ec["ta"]}).get("error", ""))
ok("criteria with a bad condition field → error", "error" in S.screen_unified(criteria={"fundamental": [{"concept": "roe", "pattern": "above", "foo": 1}]}))

# unknown TOP-LEVEL arguments are refused by the tool's argument model (not silently ignored)
am = S.mcp._tool_manager.get_tool("screen_unified").fn_metadata.arg_model
try:
    am.model_validate({"technical": "rsi below 30"}); ok("unknown top-level arg refused", False)
except Exception as e:
    ok("unknown top-level arg refused, with the allowed list", "unknown argument(s) ['technical']" in str(e) and "criteria" in str(e), str(e)[:300])
ok("known args still validate", am.model_validate({"criteria": {"ta": []}, "mode": "check"}).criteria == {"ta": []})
ok("input schema says no extra properties", S.mcp._tool_manager.get_tool("screen_unified").parameters.get("additionalProperties") is False)

print("PASS" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
