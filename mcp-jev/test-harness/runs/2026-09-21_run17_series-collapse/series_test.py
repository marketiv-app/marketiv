"""CALIBRATION (isolated — I write the args; NOT the MCP test). Measures concept→series_id + the carried transform +
variant disambiguation (headline/core, SA/NSA) + boundary. Also checks _is_series_id passthrough + recall floor.
Usage: MARKETDX_BASE_URL=http://127.0.0.1:8090 TYPESAFE_API_KEY=... uv run --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn python series_test.py
"""
import sys, os
sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
os.environ.setdefault("MARKETDX_API_KEY", "avn_live_22dc8962c39593e7a5c449ff")
import server

# (concept, country, context, kind, expect_series_id[, expect_transform])
CASES = [
    ("inflation",                 None, "how is US inflation?",            "resolve", "CPIAUCSL", "pc1"),
    ("core PCE",                  None, "core PCE trend",                  "resolve", "PCEPILFE", None),
    ("core inflation",            None, "is core inflation sticky?",       "resolve", "CPILFESL|PCEPILFE", None),
    ("unemployment rate",         None, "US unemployment rate now",        "resolve", "UNRATE", "lin"),
    ("10 year treasury yield",    None, "where is the 10y yield?",         "resolve", "DGS10", None),
    ("fed funds rate",            None, "the fed funds rate",              "resolve", "FEDFUNDS|DFF", None),
    ("ISM manufacturing PMI",     None, "ISM manufacturing PMI",           "no_match", None, None),
]

def recall_floor(concept, country, picked):
    cands = server.mdx()._get("/v1/ext/fred/find", {"q": concept, "country": country, "limit": 15}).data
    cands = cands.get("candidates") or cands.get("series") or []
    ids = [c.get("series_id") for c in cands]
    return picked in ids, ids

def run_once(label):
    print(f"\n===== {label} =====")
    npass = nfail = 0
    for concept, country, ctx, kind, expect_sid, expect_tf in CASES:
        r = server._resolve_series(concept, country=country, context=ctx)
        st = r.get("status"); sid = r.get("series_id"); tf = r.get("transform")
        if kind == "resolve":
            sid_ok = (st == "resolved" and (sid in expect_sid.split("|") if "|" in (expect_sid or "") else sid == expect_sid))
            tf_ok = (expect_tf is None or tf == expect_tf)
            floor_ok = sid_ok and recall_floor(concept, country, sid)[0]
            ok = sid_ok and tf_ok and floor_ok
        else:  # no_match
            ok = (st == "no_match")
        npass += ok; nfail += (not ok)
        got = f"{sid} tf={tf}" if st == "resolved" else st
        print(f"  [{'ok ' if ok else 'FAIL'}] {concept:24s} → {got:22s} (expect {kind}:{expect_sid} tf={expect_tf})")
    # passthrough + shape checks (no Jev)
    print(f"  _is_series_id: CPIAUCSL={server._is_series_id('CPIAUCSL')} DGS10={server._is_series_id('DGS10')} "
          f"'GDP'={server._is_series_id('GDP')} 'inflation'={server._is_series_id('inflation')} 'core PCE'={server._is_series_id('core PCE')}")
    print(f"  ---- {npass} pass / {nfail} fail ----")
    return nfail

f1 = run_once("RUN 1"); f2 = run_once("RUN 2 (stability)")
print(f"\nTOTAL fails: run1={f1} run2={f2}")
