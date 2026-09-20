"""A/B PARITY — old find_stock (candidate list, client picks) vs new _resolve_ticker (Jev picks server-side).
Both hit the SAME /v1/stocks retrieval, so the candidate set is identical → this isolates the PICK step.
Run BEFORE deleting find_stock (both callable). Metrics:
  (a) recall floor : every NEW resolved pick MUST be in OLD top_k (else the picker invented an out-of-set answer)
  (b) pick quality : NEW vs OLD rank-1 — where they differ, NEW must be the CORRECT entity (Jev beats rank-1)
  (c) gate honesty : ambiguity → NEW reconfirm (candidates ⊆ top_k); boundary → NEW no_match where OLD returned junk
Usage: MARKETDX_BASE_URL=http://127.0.0.1:8090 TYPESAFE_API_KEY=... uv run --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn python parity_test.py
"""
import sys, os
sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
os.environ.setdefault("MARKETDX_API_KEY", "avn_live_22dc8962c39593e7a5c449ff")
import server

SCOPE = server._SCOPE_BROAD  # broadest — matches find_stock's all-types candidate list

# (query, expected-correct-ticker or None, note). expected is a human judgment used to score pick-quality on disagreement.
CASES = [
    ("apple",              "AAPL.US",   "TRAP: old rank-1 = APPLE.COMM (commodity); company is rank-2"),
    ("AAPL",               "AAPL.US",   "bare symbol"),
    ("AAPL.US",            "AAPL.US",   "exact full ticker (passthrough)"),
    ("microsoft",          "MSFT.US",   "mega-cap by name"),
    ("nvidia",             "NVDA.US",   "mega-cap by name"),
    ("NVDA",               "NVDA.US",   "bare symbol"),
    ("GOOGL",              None,        "cross-listing — GOOGL class A"),
    ("GOOG",               None,        "cross-listing — GOOG class C"),
    ("Toyota",             None,        "non-US name"),
    ("SK Hynix",           None,        "non-US name (Korea)"),
    ("茅台",                None,        "non-English name (Kweichow Moutai)"),
    ("トヨタ",               None,        "non-English name (Toyota JP)"),
    ("英伟达",              "NVDA.US",   "non-English name (NVIDIA CN)"),
    ("KBANK",              None,        "SAME-NAME across markets (Thai KBANK.BK vs Korean Kbank) → expect reconfirm"),
    ("chip maker",         None,        "phrase → semantic"),
    ("gold",               None,        "commodity concept"),
    ("copper",             None,        "commodity concept"),
    ("bitcoin",            None,        "crypto"),
    ("US 10 year treasury",None,        "bond yield (.GB, type=stock)"),
    ("SOFR",               None,        "money-market rate (.MM)"),
    ("openai",             None,        "private / off-coverage"),
    ("my lucky ticker",    None,        "BOUNDARY — not a company → expect no_match"),
    ("asdfghjkl",          None,        "BOUNDARY — junk → expect no_match"),
    ("the stock that will go up", None, "BOUNDARY — not an entity → expect no_match"),
]

def old_topk(q):
    # OLD find_stock = GET /v1/stocks?q=…&limit=8 → the candidate list the client picked from. find_stock the TOOL is
    # now deleted, but the endpoint (its retrieval) stays — call it directly to reproduce the old top_k for parity.
    rows = server.mdx()._get("/v1/stocks", {"q": q, "limit": 8}).data.get("matches", [])
    return [m.get("ticker") for m in rows if m.get("ticker")]

recall_fail, disagree, reconfirm, no_match, resolved = [], [], [], [], []
print(f"{'query':26s} {'OLD rank-1':16s} {'NEW pick/status':18s} {'in_topk':7s} note")
print("-" * 110)
for q, exp, note in CASES:
    top = old_topk(q)
    r = server._resolve_ticker(q, scope=SCOPE)
    st = r.get("status")
    if st == "resolved":
        pick = r.get("ticker"); intop = pick in top
        resolved.append(q)
        if not intop: recall_fail.append((q, pick, top))
        agree = (pick == (top[0] if top else None))
        if not agree: disagree.append((q, top[0] if top else None, pick, exp))
        flag = "YES" if intop else "🔴NO"
        mark = "" if agree else ("  ✅NEW-better" if (exp and pick == exp) else "  ⚠️differs")
        print(f"{q:26s} {(top[0] if top else '-'):16s} {pick:18s} {flag:7s} {note}{mark}")
    elif st == "reconfirm":
        reconfirm.append(q)
        cands = [c.get("ticker") for c in r.get("candidates", [])]
        subset = all(c in top for c in cands)
        print(f"{q:26s} {(top[0] if top else '-'):16s} {'RECONFIRM':18s} {'⊆'if subset else '🔴':7s} {note}  cands={cands}")
    else:  # no_match
        no_match.append(q)
        print(f"{q:26s} {(top[0] if top else '-'):16s} {'NO_MATCH':18s} {'-':7s} {note}  (old junk top-1={top[0] if top else None})")

print("-" * 110)
print(f"resolved={len(resolved)}  reconfirm={len(reconfirm)}  no_match={len(no_match)}")
print(f"🔴 RECALL-FLOOR failures (NEW pick NOT in OLD top_k): {len(recall_fail)} {recall_fail}")
print(f"DISAGREEMENTS (NEW != OLD rank-1): {len(disagree)}")
for q, o, n, exp in disagree:
    verdict = "NEW correct" if (exp and n == exp) else ("OLD rank-1 was junk" if exp is None else f"CHECK (exp={exp})")
    print(f"    {q:24s} old#1={o:16s} new={n:16s} → {verdict}")
assert not recall_fail, f"RECALL FLOOR VIOLATED: {recall_fail}"
print("\n✅ recall floor holds (every NEW resolved pick ∈ OLD top_k).")

# ── SCOPE EFFECT — the value the collapse adds that flat find_stock (no scope) CANNOT: the SAME word resolves
#    differently per consuming tool's scope, so the client never has to disambiguate an out-of-scope candidate.
print("\n" + "=" * 70 + "\nSCOPE EFFECT (per-consumer scope filters the candidate set):")
SCOPES = [("stock-only (financials)", server._SCOPE_STOCK), ("asset (asset_pulse)", server._SCOPE_ASSET),
          ("broad (stock_prices)", server._SCOPE_BROAD)]
for q in ["apple", "gold"]:
    print(f"  '{q}':")
    for label, sc in SCOPES:
        r = server._resolve_ticker(q, scope=sc)
        print(f"      {label:26s} → {r.get('status'):9s} {r.get('ticker') or ''}")

