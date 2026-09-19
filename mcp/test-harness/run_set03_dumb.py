#!/usr/bin/env python
"""Dumb-client driver for set-03-fundamental-novice. MCP protocol only."""
import os, sys, json, asyncio, datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8901/mcp")
BEARER = os.environ.get("BEARER", "")
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}
OUT = "/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-03"

# Each case: id, question, list of (tool, args), and an answer builder(results)->str
CASES = []

def add(cid, question, calls, answer):
    CASES.append({"id": cid, "question": question, "calls": calls, "answer": answer})

# fn-01 big well-known companies, not too expensive: large size, low PE (below average), big absolute mcap
add("fn-01",
    "I'm just starting out. Can you find me some big, well-known companies that aren't too expensive right now?",
    [("screen_unified", {
        "fundamental": [{"concept": "pe", "pattern": "below_average"}],
        "size": ["large"],
        "min_market_cap_usd": 100000000000,
        "country": ["US"],
        "sort": "mcap",
        "limit": 10
    })],
    None)

# fn-02 good dividend but safe/stable: established dividend payers, moderate yield, streak, payout not stretched
add("fn-02",
    "Which companies pay a good dividend but are also safe and stable? I don't want anything risky.",
    [("screen_dividends", {
        "country": "US",
        "min_yield": 3,
        "max_yield": 8,
        "min_streak_years": 5,
        "max_payout": 0.75,
        "min_market_cap_usd": 20000000000,
        "order_by": "streak",
        "limit": 15
    })],
    None)

# fn-03 Is Apple expensive: resolve then financials + asset_pulse
add("fn-03",
    "Is Apple expensive right now?",
    [("find_stock", {"q": "Apple"}),
     ("financials", {"tickers": "AAPL.US", "period": "5y"}),
     ("asset_pulse", {"ticker": "AAPL.US", "window": "90d"})],
    None)

# fn-04 companies that make more money every year (profits keep going up): improved net income + revenue up every year
add("fn-04",
    "Show me companies that make more money every year — like their profits keep going up.",
    [("screen_unified", {
        "fundamental": [
            {"concept": "net_income", "pattern": "improved_every_year", "params": {"N": 3}}
        ],
        "size": ["large"],
        "sort": "mcap",
        "limit": 12
    })],
    None)

# fn-05 Thai stable dividend long hold (in Thai)
add("fn-05",
    "หุ้นไทยตัวไหนที่มั่นคง ปันผลดี น่าถือยาว บ้าง",
    [("screen_dividends", {
        "country": "TH",
        "min_yield": 3,
        "max_yield": 10,
        "min_streak_years": 3,
        "max_payout": 0.85,
        "min_market_cap_usd": 1000000000,
        "order_by": "streak",
        "limit": 15
    })],
    None)

# fn-06 solid companies with low debt
add("fn-06",
    "I keep hearing 'don't buy companies with too much debt.' Can you find me some solid companies that don't have much debt?",
    [("screen_unified", {
        "fundamental": [
            {"concept": "debt_to_equity", "pattern": "below", "params": {"threshold": 0.3}},
            {"concept": "roe", "pattern": "above_average"}
        ],
        "size": ["large"],
        "country": ["US"],
        "sort": "mcap",
        "limit": 12
    })],
    None)

# fn-07 Is Tesla a good company: resolve + financials + asset_pulse
add("fn-07",
    "Is Tesla a good company to invest in?",
    [("find_stock", {"q": "Tesla"}),
     ("financials", {"tickers": "TSLA.US", "period": "5y"}),
     ("asset_pulse", {"ticker": "TSLA.US", "window": "90d"})],
    None)

# fn-08 quality: high ROE, cheap-ish PE below avg, growing revenue, low debt
add("fn-08",
    "I want quality — companies that are really good at making profit from what they own, cheap-ish, growing, and not drowning in debt. Give me a few.",
    [("screen_unified", {
        "fundamental": [
            {"concept": "roe", "pattern": "above_average"},
            {"concept": "pe", "pattern": "below_average"},
            {"concept": "revenue", "pattern": "consecutive_growth", "params": {"N": 3, "threshold": 0.05}},
            {"concept": "debt_to_equity", "pattern": "below", "params": {"threshold": 0.5}}
        ],
        "size": ["large"],
        "sort": "mcap",
        "limit": 10
    })],
    None)

# fn-09 Thai: safe alternatives beyond stocks (bonds, funds) - resolve a bond/gold proxy + bond_pulse
add("fn-09",
    "ถ้าอยากลงทุนแบบปลอดภัยไม่อยากขาดทุน มีทางเลือกอะไรบ้างนอกจากหุ้น เช่นพวกที่เสี่ยงน้อยๆ",
    [("find_stock", {"q": "US 10 year treasury bond yield"}),
     ("bond_pulse", {"q": "US yield curve"}),
     ("find_stock", {"q": "US treasury bond ETF"})],
    None)

# fn-10 gold as safe haven + how to invest
add("fn-10",
    "My friend said gold is a safe place to put money when things get scary. Is that true, and how would I even invest in it?",
    [("find_stock", {"q": "gold"}),
     ("commodity_pulse", {"q": "gold"}),
     ("find_stock", {"q": "gold ETF"})],
    None)


async def run():
    results_summary = []
    async with streamablehttp_client(URL, headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            only = set(sys.argv[1:])
            for case in CASES:
                if only and case["id"] not in only:
                    continue
                tools_called = []
                raw_responses = []
                names = []
                errflag = ""
                for tool, args in case["calls"]:
                    names.append(tool)
                    tools_called.append({"tool": tool, "args": args})
                    try:
                        res = await s.call_tool(tool, args,
                                                read_timeout_seconds=datetime.timedelta(seconds=115))
                        texts = []
                        for c in res.content:
                            texts.append(getattr(c, "text", str(c)))
                        joined = "\n".join(texts)
                        try:
                            parsed = json.loads(joined)
                        except Exception:
                            parsed = joined
                        if res.isError:
                            errflag = "ERR"
                            raw_responses.append({"_isError": True, "content": parsed})
                        else:
                            raw_responses.append(parsed)
                    except Exception as e:
                        errflag = "EXC"
                        raw_responses.append({"_exception": repr(e), "_args": args})
                # crude count for stdout
                cnt = ""
                for rr in raw_responses:
                    if isinstance(rr, dict):
                        for k in ("count", "results", "rows", "matches", "candidates"):
                            v = rr.get(k)
                            if isinstance(v, list):
                                cnt = f"{k}={len(v)}"; break
                            if isinstance(v, int):
                                cnt = f"{k}={v}"; break
                        if cnt: break
                out = {
                    "id": case["id"],
                    "question": case["question"],
                    "tools_called": tools_called,
                    "raw_responses": raw_responses,
                    "answer_to_user": ""  # filled later manually per case
                }
                path = os.path.join(OUT, f"{case['id']}.json")
                with open(path, "w") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                results_summary.append((case["id"], "+".join(names), errflag or cnt, case["question"][:60]))
    for cid, tl, c, q in results_summary:
        print(f"{cid} | tools={tl} | count/err={c} | q={q}")

if __name__ == "__main__":
    asyncio.run(run())
