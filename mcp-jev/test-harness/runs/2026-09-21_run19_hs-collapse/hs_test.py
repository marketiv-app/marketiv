"""CALIBRATION (isolated — I write args; NOT the MCP test). concept→HS/EBOPS code + SUPPLY-STAGE disambiguation
(ore vs refined via context) + leaf/roll-up + goods/services type + boundary + recall floor + _is_hs_code passthrough.
Usage: MARKETDX_BASE_URL=http://127.0.0.1:8090 TYPESAFE_API_KEY=... uv run --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn python hs_test.py
"""
import sys, os, re
sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
os.environ.setdefault("MARKETDX_API_KEY", "avn_live_22dc8962c39593e7a5c449ff")
import server

# (concept, type, context, kind, expect_code_prefix_regex)
CASES = [
    ("crude oil",      "goods",    "how much crude oil was exported",          "resolve", r"^2709"),
    ("copper ore",     "goods",    "top copper ORE exporters",                 "resolve", r"^2603"),
    ("refined copper", "goods",    "refined copper cathode trade",             "resolve", r"^74"),
    ("rice",           "goods",    "total rice exports (all rice)",            "resolve", r"^1006"),   # roll-up to the family
    ("integrated circuits","goods","integrated circuit / chip exports",        "resolve", r"^8542"),
    ("tourism",        "services", "tourism / travel services exports",        "resolve", r"^2"),   # EBOPS travel (236)
    ("my favorite hobby", "goods", "my favorite hobby",                        "no_match", None),
]

def recall_floor(concept, t, picked):
    # a resolved pick must be a candidate code OR a candidate's 4-digit parent (the roll-up aggregate).
    d = server.mdx()._get("/v1/ext/hs/find", {"q": concept, "type": t, "limit": 15}).data
    cands = d.get("candidates") or []
    ok_set = {c.get("code") for c in cands} | {str(c.get("parent_code")) for c in cands if c.get("parent_code")}
    return picked in ok_set

def run_once(label):
    print(f"\n===== {label} =====")
    npass = nfail = 0
    for concept, t, ctx, kind, expect in CASES:
        r = server._resolve_hs(concept, type=t, context=ctx)
        st = r.get("status"); code = r.get("code")
        if kind == "resolve":
            ok = (st == "resolved" and code and re.search(expect, str(code))) and recall_floor(concept, t, code)
        else:
            ok = (st == "no_match")
        npass += bool(ok); nfail += (not ok)
        got = f"{code} ({r.get('title','')[:30]})" if st == "resolved" else st
        print(f"  [{'ok ' if ok else 'FAIL'}] {concept:16s} [{t:8s}] → {got:42s} (expect {kind}:{expect})")
    print(f"  _is_hs_code: 2709={server._is_hs_code('2709')} '0207,0203'={server._is_hs_code('0207,0203')} "
          f"'crude oil'={server._is_hs_code('crude oil')}")
    print(f"  ---- {npass} pass / {nfail} fail ----")
    return nfail

f1 = run_once("RUN 1"); f2 = run_once("RUN 2 (stability)")
print(f"\nTOTAL fails: run1={f1} run2={f2}")
