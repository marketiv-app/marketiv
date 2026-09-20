"""Resolver case-matrix for the RECONFIRM-on-ambiguity fix. Probes _resolve_ticker(q, scope=broad) with the QUERY as
the context Jev sees, and asserts resolve-vs-reconfirm + the picked ticker / the tied candidate set.
Principle: query signals a kind/name → RESOLVE the right one; a bare genuinely-split word → RECONFIRM the tied set;
a bare word with one dominant everyday meaning → RESOLVE it (controls must NOT over-reconfirm).
Usage: MARKETDX_BASE_URL=http://127.0.0.1:8090 TYPESAFE_API_KEY=... uv run --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn python reconfirm_test.py
"""
import sys, os
sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
os.environ.setdefault("MARKETDX_API_KEY", "avn_live_22dc8962c39593e7a5c449ff")
import server
SCOPE = server._SCOPE_BROAD

# DECISION (ran): resolve to the DOMINANT everyday reading (99% intent, best UX); the 1% corrects in conversation.
# RECONFIRM only when Jev is genuinely unsure (no dominant reading — a real KIND/entity tie). Fast-path only for an
# ALL-UPPERCASE deliberate ticker symbol (a lowercase common word defers to Jev, which reads its meaning).
# each: (query, kind, expect). kind='resolve'→expect=ticker · 'reconfirm'→expect=set that MUST ⊆ candidates · 'soft'→informational
CASES = [
    # (A) query SIGNALS which one → RESOLVE the right one
    ("apple stock",                              "resolve",   "AAPL.US"),
    ("apple the company",                        "resolve",   "AAPL.US"),
    ("apple as a commodity",                     "resolve",   "APPLE.COMM"),
    ("Samsung Electronics",                      "resolve",   "005930.KO"),
    ("Samsung Biologics",                        "resolve",   "207940.KO"),
    # (B) BARE word → RESOLVE the DOMINANT reading (99% intent); fast-path bug fixed so apple is NOT the fruit commodity
    ("apple",                                    "resolve",   "AAPL.US"),      # the company, not APPLE.COMM (Fuji fruit)
    ("samsung",                                  "resolve",   "005930.KO"),    # Samsung Electronics (dominant)
    ("gold",                                     "resolve",   "GOLD.COMM"),    # the commodity dominates
    ("Toyota",                                   "resolve",   "7203.JP"),
    ("microsoft",                                "resolve",   "MSFT.US"),
    ("NVDA",                                     "resolve",   "NVDA.US"),      # uppercase → fast-path
    ("bitcoin",                                  "resolve",   "BTC-USD.CC"),
    ("AAPL.US",                                  "resolve",   "AAPL.US"),      # exact → passthrough
    # (C) genuinely-unsure (no dominant reading, a real tie) → RECONFIRM
    ("SOFR",                                     "reconfirm", {"SOFR.MM"}),    # rate .MM vs SOFR.US vs USSOFR.MM — Jev unsure
]

def run_once(label):
    print(f"\n===== {label} =====")
    npass = nfail = 0
    for q, kind, expect in CASES:
        r = server._resolve_ticker(q, scope=SCOPE)
        st = r.get("status")
        cands = {c.get("ticker") for c in r.get("candidates", [])}
        if kind == "resolve":
            ok = (st == "resolved" and r.get("ticker") == expect)
            got = r.get("ticker") if st == "resolved" else f"{st} {sorted(cands)}"
        elif kind == "reconfirm":
            ok = (st == "reconfirm" and expect <= cands)
            got = f"{st} cands={sorted(cands)}"
        else:  # soft
            ok = True
            got = r.get("ticker") if st == "resolved" else f"{st} {sorted(cands)}"
        flag = "ok " if ok else "FAIL"
        if kind != "soft":
            npass += ok; nfail += (not ok)
        print(f"  [{flag}] {q:44s} expect {kind}:{expect if not isinstance(expect,set) else sorted(expect)} → {got}")
    print(f"  ---- {npass} pass / {nfail} fail (soft rows excluded) ----")
    return nfail

f1 = run_once("RUN 1")
f2 = run_once("RUN 2 (stability — Jev is non-deterministic)")
print(f"\nTOTAL fails: run1={f1} run2={f2}")
