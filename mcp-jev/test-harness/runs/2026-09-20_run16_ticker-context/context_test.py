"""CALIBRATION (isolated — I write the args; NOT the MCP test). Measures the entity/context split: retrieval on the
ENTITY, Jev judges with the CONTEXT (the user's full request). + the language rule (native names / English concepts).
Usage: MARKETDX_BASE_URL=http://127.0.0.1:8090 TYPESAFE_API_KEY=... uv run --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn python context_test.py
"""
import sys, os
sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
os.environ.setdefault("MARKETDX_API_KEY", "avn_live_22dc8962c39593e7a5c449ff")
import server
SCOPE = server._SCOPE_BROAD

# (entity, context, kind, expect)
CASES = [
    # 🔴 the failing case: context "fruit" → the commodity
    ("apple", "ขอราคาผลไม้ apple",              "resolve", "APPLE.COMM"),
    ("apple", "price of the fruit apple",       "resolve", "APPLE.COMM"),
    ("apple", "apple stock price",              "resolve", "AAPL.US"),
    ("apple", "apple the company earnings",     "resolve", "AAPL.US"),
    ("apple", None,                             "resolve", "AAPL.US"),      # no ctx → dominant (decision a)
    # compound — same context shared; wheat frames apple as an agri commodity
    ("wheat", "price of wheat and apple",       "resolve", "WHEAT.COMM"),
    ("apple", "price of wheat and apple",       "resolve", "APPLE.COMM"),
    # LANGUAGE: native company NAMES resolve as-is
    ("茅台",   "ราคาหุ้น 茅台",                    "resolve", "600519.CG"),
    ("トヨタ",  "トヨタの株価",                      "resolve", "7203.JP"),
    ("삼성전자","삼성전자 실적",                     "resolve", "005930.KO"),
    # LANGUAGE: English commodity concept resolves (native would drift — that's the client's job to translate)
    ("gold",  "gold price",                     "resolve", "GOLD.COMM"),
    ("crude oil", "crude oil price",            "resolve", "WTI.COMM|BRENT.COMM"),
    # controls
    ("NVDA",  "NVDA price",                     "resolve", "NVDA.US"),
    ("Toyota","how is Toyota trading",          "resolve", "7203.JP"),
]

def run_once(label):
    print(f"\n===== {label} =====")
    npass = nfail = 0
    for ent, ctx, kind, expect in CASES:
        r = server._resolve_ticker(ent, scope=SCOPE, context=ctx)
        st = r.get("status"); tk = r.get("ticker")
        ok = (st == "resolved" and (tk in expect.split("|") if "|" in expect else tk == expect))
        npass += ok; nfail += (not ok)
        got = tk if st == "resolved" else f"{st} {[c.get('ticker') for c in r.get('candidates',[])]}"
        print(f"  [{'ok ' if ok else 'FAIL'}] entity={ent:9s} ctx={str(ctx)[:28]:28s} → {got:14s} (expect {expect})")
    print(f"  ---- {npass} pass / {nfail} fail ----")
    return nfail

f1 = run_once("RUN 1"); f2 = run_once("RUN 2 (stability)")
print(f"\nTOTAL fails: run1={f1} run2={f2}")
