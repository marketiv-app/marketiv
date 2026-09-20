"""CALIBRATION (isolated — I write args; NOT the MCP test). concept→indicator + carried database + unit VARIANT
disambiguation (%GDP/US$/per-capita/constant) + boundary + recall floor + _is_indicator_id passthrough.
Usage: MARKETDX_BASE_URL=http://127.0.0.1:8090 TYPESAFE_API_KEY=... uv run --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn python indicator_test.py
"""
import sys, os
sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
os.environ.setdefault("MARKETDX_API_KEY", "avn_live_22dc8962c39593e7a5c449ff")
import server

# (concept, context, kind, expect_indicator_substr)
CASES = [
    ("household consumption as % of GDP", "compare household spending as a share of GDP", "resolve", "CON_PRVT.*ZS|CON_PRVT_ZS"),
    ("GDP per capita",                    "GDP per capita in current dollars",            "resolve", "GDP_PCAP_CD"),
    ("GDP per capita in real terms",      "real GDP per capita over time",                "resolve", "GDP_PCAP_KD"),
    ("life expectancy",                   "life expectancy at birth",                     "resolve", "DYN_LE00"),
    ("government debt as % of GDP",       "government debt to GDP ratio",                 "resolve", "GC_DOD|CENT_DEBT|DOD_TOTL_GD_ZS"),
    ("annual inflation rate",             "Thailand annual inflation over the years",     "resolve", "FP_CPI_TOTL_ZG"),
    ("Nvidia stock price",                "what is Nvidia's stock price",                 "no_match", None),
    ("Apple quarterly revenue",           "Apple's latest quarterly revenue",             "no_match", None),
]

import re
def recall_floor(concept, picked):
    d = server.mdx()._get("/v1/ext/wb/find", {"q": concept, "limit": 15}).data
    cands = d.get("candidates") or d.get("indicators") or []
    return picked in [c.get("indicator") for c in cands]

def run_once(label):
    print(f"\n===== {label} =====")
    npass = nfail = 0
    for concept, ctx, kind, expect in CASES:
        r = server._resolve_indicator(concept, context=ctx)
        st = r.get("status"); ind = r.get("indicator"); db = r.get("database")
        if kind == "resolve":
            sid_ok = (st == "resolved" and ind and re.search(expect, ind))
            ok = bool(sid_ok) and recall_floor(concept, ind)
        else:
            ok = (st == "no_match")
        npass += ok; nfail += (not ok)
        got = f"{ind} db={db}" if st == "resolved" else st
        print(f"  [{'ok ' if ok else 'FAIL'}] {concept:38s} → {got:34s} (expect {kind}:{expect})")
    print(f"  _is_indicator_id: WB_WDI_NE_CON_PRVT_ZS={server._is_indicator_id('WB_WDI_NE_CON_PRVT_ZS')} "
          f"'GDP per capita'={server._is_indicator_id('GDP per capita')} 'consumption'={server._is_indicator_id('consumption')}")
    print(f"  ---- {npass} pass / {nfail} fail ----")
    return nfail

f1 = run_once("RUN 1"); f2 = run_once("RUN 2 (stability)")
print(f"\nTOTAL fails: run1={f1} run2={f2}")
