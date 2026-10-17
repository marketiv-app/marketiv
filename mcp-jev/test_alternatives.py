"""Unit test: alternatives for an unsupported TA condition are DATA from the engine (R1 allowed values, R2 other
patterns on the same operands), in schema order, nothing ranked. Offline: SCREEN_SCHEMA_FILE=<saved /v1/screen/schema>.
Run: SCREEN_SCHEMA_FILE=schema.json uv run python test_alternatives.py"""
import os, sys
assert os.environ.get("SCREEN_SCHEMA_FILE"), "set SCREEN_SCHEMA_FILE to a saved copy of GET /v1/screen/schema"
import server as S

fails = 0
def ok(name, cond, info=None):
    global fails
    if not cond: fails += 1; print("FAIL", name, info if info is not None else "")

# R1 from mdx-api's structured `allowed`, R2 from the schema (a pattern whose b pairs with close — any a it takes)
e_new = {"code": "unsupported_pair", "message": "near-MA pullback is not tracked for 'ema20' — available reference operands: [\"ema50\", \"ema200\", \"sma200\"]",
         "allowed": {"operand": "b", "values": ["ema50", "ema200", "sma200"]}}
r = S._ta_alternatives({"pattern": "near_ma", "b": "ema20"}, S._allowed_of(e_new))
near, meta = r["nearest"], r["nearest_meta"]
ok("R1 first, the allowed lines, same pattern", near[:3] == [{"pattern": "near_ma", "b": x} for x in ("ema50", "ema200", "sma200")], near[:3])
ok("every item has its rule and meaning", len(meta) == len(near) and all(m["rule"] and m["means"] for m in meta), meta)
r2 = [n for n, m in zip(near, meta) if m["rule"].startswith("same operands")]
ok("R2 keeps the user's b", r2 and all(n.get("b") == "ema20" for n in r2), r2)
ok("R2 only patterns that accept that b (schema)", all(S._pairs_for(dict((p, o) for p, o, _, _ in S._S["ta_ops"])[n["pattern"]], n.get("a"), "ema20") for n in r2))
order = [p for p, _, _, _ in S._S["ta_ops"]]
idx = [order.index(n["pattern"]) for n in r2]
ok("R2 in schema order", idx == sorted(idx), idx)
ok("no converge close/ema20 (the engine does not run it)", not any(n["pattern"] == "converge" and n.get("a") == "close" and n.get("b") == "ema20" for n in near))
print("  near_ma ema20 →", near, "capped" if r.get("nearest_capped") else "")

# older mdx-api: no `allowed`, the same list read from the message
ok("fallback to the message list", S._allowed_of({"message": "no crossover_up cross of 'ema50' — available reference operands: [\"ema100\", \"ema200\"]"})
   == {"operand": "b", "values": ["ema100", "ema200"]})
ok("operand a from 'available on'", S._allowed_of({"message": "regular divergence is available on: [\"rsi14\",\"macd_line\"] (got 'stoch_k')"})
   == {"operand": "a", "values": ["rsi14", "macd_line"]})
ok("no list → None", S._allowed_of({"message": "unknown pattern"}) is None)

# a known a: R2 keeps BOTH operands (strict pair); the user's timeframe goes with patterns that take it
r = S._ta_alternatives({"pattern": "crossover_up", "a": "ema50", "b": "ema20", "timeframe": 2}, {"operand": "b", "values": ["ema100", "ema200"]})
ok("R1 keeps the user's other settings", r["nearest"][0] == {"pattern": "crossover_up", "a": "ema50", "b": "ema100", "timeframe": 2}, r["nearest"][:2])
for n, m in zip(r["nearest"], r["nearest_meta"]):
    if m["rule"].startswith("same operands"):
        ok("R2 strict pair", n.get("a") == "ema50" and n.get("b") == "ema20", n)
print("  crossover ema50/ema20 →", r["nearest"])

# a level b (RSI 35): patterns whose b levels take 35
r = S._ta_alternatives({"pattern": "touch_up", "a": "rsi14", "b": "35"}, None)
ok("level b matched by levels", r["nearest"] and all(n.get("a") == "rsi14" for n in r["nearest"]), r)

# the size cap is a bound, said when hit
S._ALT_CAP, cap0 = 2, S._ALT_CAP
r = S._ta_alternatives({"pattern": "near_ma", "b": "ema20"}, S._allowed_of(e_new))
ok("cap said when hit", len(r["nearest"]) == 2 and r.get("nearest_capped") and r["nearest_total"] > 2, r)
S._ALT_CAP = cap0
ok("an OR list / no pattern → None", S._ta_alternatives([{"pattern": "x"}], None) is None and S._ta_alternatives({}, None) is None)

print("PASS" if not fails else f"{fails} failed"); sys.exit(1 if fails else 0)
