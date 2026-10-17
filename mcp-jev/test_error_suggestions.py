"""Unit test: ONE error→suggestion mapping for both MCP paths — the builder route (/v1/screen/resolve → _frag_finish)
and the screen_unified tool's failure path (_screen_fixable_400). The same validate error → the same `nearest` data.
Offline: SCREEN_SCHEMA_FILE=<saved /v1/screen/schema>; validate is stubbed with fixture errors.
Run: SCREEN_SCHEMA_FILE=schema.json uv run --no-project --python 3.12 --with 'mcp<2',openai,uvicorn --with-editable ../python python test_error_suggestions.py"""
import os, sys
assert os.environ.get("SCREEN_SCHEMA_FILE")
import server as S

fails = 0
def ok(name, cond, info=None):
    global fails
    if not cond: fails += 1; print("FAIL", name, info if info is not None else "")

KEYS = ("nearest", "nearest_meta", "nearest_capped", "nearest_total", "needed", "available", "max")
pick = lambda d: {k: d[k] for k in KEYS if d.get(k) not in (None, [])}

def via_resolve(sig, err, leg="ta"):
    ctx = {"res": {"phrase": "x"}, "leg": leg, "place": {"leg": leg, "rel": "new"}, "key_val": sig, "path": "ta[0]" if leg == "ta" else "fundamental[0]",
           "notes": [], "raw_ops": {}, "texts": []}
    return S._frag_finish(ctx, {"errors": [err], "snaps": [], "assumed": [], "notes": []}, {"assumed": [], "notes": []})

def via_screen(body, err, alone=None):
    calls = []
    def fake(batch):
        calls.append(batch)
        if len(calls) == 1: return [{"valid": False, "errors": [err]}]
        return alone(batch)
    S._screen_validate_batch, keep = fake, S._screen_validate_batch
    try: return S._screen_fixable_400(body)
    finally: S._screen_validate_batch = keep

DIV = {"code": "operand_not_for_pattern", "path": "ta[0].anchor", "message": "step 0 anchor: regular divergence is available on: [\"rsi14\",\"macd_line\"] (got 'stoch_k')",
       "allowed": {"operand": "a", "values": ["rsi14", "macd_line"]}}
PAIR = {"code": "unsupported_pair", "path": "ta[0].anchor", "message": "step 0 anchor: no crossover_up cross of 'ema5' — available reference operands: []",
        "allowed": {"operand": "b", "values": []}}
TF = {"code": "anchor_tf_mismatch", "path": "ta[0].anchor", "message": "step 0 anchor: per-condition timeframe (2) must match the request timeframe (1)"}
HIST = {"code": "insufficient_history", "path": "fundamental", "message": "needs 10 annual periods, deepest 6", "needed": 10, "available": 6, "max": 6,
        "nearest": [{"concept": "net_income", "pattern": "consecutive_growth", "params": {"n": 6}}]}
cases = [
    ("divergence on stoch", {"pattern": "divergence_bull", "a": "stoch_k"}, DIV, "ta"),
    ("crossover with no stored partner", {"pattern": "crossover_up", "a": "ema5", "b": "sma200"}, PAIR, "ta"),
    ("anchor on another chart", {"pattern": "above", "a": "close", "b": "ema200", "timeframe": 2}, TF, "ta"),
    ("insufficient history", {"concept": "net_income", "pattern": "consecutive_growth", "params": {"n": 10}}, HIST, "fundamental"),
]
for name, sig, err, leg in cases:
    r = via_resolve(sig, err, leg)
    body = {"ta": [{"anchor": [sig]}]} if leg == "ta" else {"fundamental": [sig]}
    u = via_screen(body, err)
    ok(f"{name}: screen_unified answers needs_rewrite", u and u.get("needs_rewrite") and u.get("code") == err["code"], u)
    ok(f"{name}: same nearest data both paths", u and pick(r) == pick(u), (pick(r), pick(u) if u else None))
    ok(f"{name}: a guide for the LLM", u and u.get("_guide"), u)
    print(f"  {name}: nearest = {pick(u).get('nearest') if u else None}")

# today's guide codes keep their texts (no second table): state_as_step has no data, only the guide
SAS = {"code": "state_as_step", "path": "ta[0].anchor", "message": "a STATE can't be a step"}
u = via_screen({"ta": [{"anchor": [{"pattern": "above", "a": "close", "b": "ema200"}]}, {"anchor": [{"pattern": "crossover_up", "a": "macd_line", "b": "macd_signal"}]}]}, SAS)
ok("state_as_step keeps its guide", u and "STATE" in u["_guide"] and "nearest" not in u, u)
# an error nobody can act on → None (a plain 400, as before)
ok("unknown code → None", via_screen({"ta": [{"anchor": [{"pattern": "x"}]}]}, {"code": "invalid", "path": "ta[0].anchor", "message": "?"}) is None)
# an OR anchor: the failing term is found by validating each alone, and the alternatives are for THAT term
body = {"ta": [{"anchor": [{"pattern": "above", "a": "close", "b": "ema200"}, {"pattern": "divergence_bull", "a": "stoch_k"}]}]}
u = via_screen(body, DIV, alone=lambda batch: [{"valid": True, "errors": []}, {"valid": False, "errors": [DIV]}])
ok("OR anchor: the failing term located", u and u.get("at") == "ta[0].anchor[1]" and pick(u) == pick(via_resolve({"pattern": "divergence_bull", "a": "stoch_k"}, DIV)), u)

print("PASS" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
