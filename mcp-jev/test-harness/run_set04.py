#!/usr/bin/env python
"""Set-04 fundamental-expert dumb-client runner. Runs each case's tool calls, saves full raw."""
import os, sys, json, asyncio, datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8901/mcp")
BEARER = os.environ.get("BEARER", "")
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}
RAW = "/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-04"

QUESTIONS = {
 "fe-01":"Find companies globally with revenue above $5B, gross margin over 60%, operating margin over 25%, and net debt/EBITDA under 1.0x. I want large, high-margin, lightly-levered businesses.",
 "fe-02":"หาหุ้นที่มีรายได้เติบโต YoY ติดต่อกันอย่างน้อย 5 ปี และกำไรต่อหุ้น (EPS) ก็โตทุกปีในช่วงเดียวกันด้วย ขอเฉพาะบริษัทที่มีรายได้เกิน 1 พันล้านดอลลาร์",
 "fe-03":"Compare Toyota, Volkswagen, and General Motors on revenue, net income, operating margin, ROE, and net debt — all in USD so it's apples-to-apples. Which has the strongest balance sheet?",
 "fe-04":"Screen for stocks trading below their sector's average P/E but with ROE above the sector average — cheap relative to peers yet more profitable. Restrict to US large caps.",
 "fe-05":"I want accelerating growth: companies whose revenue growth rate this year is higher than last year's, and last year's was higher than the year before. So growth is speeding up, not just positive.",
 "fe-06":"Find profitable software companies with free cash flow above $500M, FCF yield above 4%, and net cash on the balance sheet (more cash than total debt). Any market.",
 "fe-07":"Show me companies with expanding margins: gross margin, operating margin, and net margin all higher today than they were three years ago. I care about the trend, not the absolute level.",
 "fe-08":"ขอบริษัทในเอเชียที่มี ROIC เกิน 15% ต่อเนื่อง, อัตราส่วนหนี้สินต่อทุน (D/E) ต่ำกว่า 0.5 เท่า, และงบดุลแข็งแรง current ratio มากกว่า 2 — เน้นคุณภาพงบดุลและผลตอบแทนจากเงินทุน",
 "fe-09":"Screen for companies with revenue over $10B that spend more than $2B a year on R&D and whose R&D as a percent of revenue is above 15% — heavy, committed innovators at scale.",
 "fe-10":"I'm hunting compounders: 3-year revenue CAGR above 20%, EPS CAGR above 25% (so earnings growing faster than sales — margin leverage), ROE consistently over 20%, and net debt/EBITDA under 2x. Global, any sector.",
}

# Each case = list of (tool, args). Answers filled after seeing results.
PLAN = {
 "fe-01":[("screen_unified",{
    "fundamental":[
      {"concept":"revenue","pattern":"above","threshold":5000000000},
      {"concept":"gross_margin","pattern":"above","threshold":0.60},
      {"concept":"operating_margin","pattern":"above","threshold":0.25},
      {"concept":"net_debt_ebitda","pattern":"below","threshold":1.0}],
    "asset_type":["Common Stock"],"limit":15})],
 "fe-02":[("screen_unified",{
    "fundamental":[
      {"concept":"revenue","pattern":"consecutive_growth","N":5},
      {"concept":"eps_diluted","pattern":"consecutive_growth","N":5},
      {"concept":"revenue","pattern":"above","threshold":1000000000}],
    "asset_type":["Common Stock"],"limit":15})],
 "fe-03":[("find_stock",{"q":"Toyota Motor"}),
          ("find_stock",{"q":"Volkswagen"}),
          ("find_stock",{"q":"General Motors"})],  # then financials with resolved tickers
 "fe-04":[("screen_unified",{
    "fundamental":[
      {"concept":"pe","pattern":"below_average","vs_cohort":{"own":True}},
      {"concept":"roe","pattern":"above_average","vs_cohort":{"own":True}}],
    "country":["US"],"size":["large"],"asset_type":["Common Stock"],"limit":15})],
 "fe-05":[("screen_unified",{
    "fundamental":[
      {"concept":"revenue","pattern":"accelerating","N":2}],
    "asset_type":["Common Stock"],"limit":15})],
 "fe-06":[("screen_unified",{
    "fundamental":[
      {"concept":"free_cash_flow","pattern":"above","threshold":500000000},
      {"concept":"fcf_yield","pattern":"above","threshold":0.04},
      {"metricA":"cash","relation":"higher_than","metricB":"total_debt","multiple":1},
      {"concept":"net_income","pattern":"above","threshold":0}],
    "gics":"4510","asset_type":["Common Stock"],"limit":15})],
 "fe-07":[("screen_unified",{
    "fundamental":[
      {"metricA":"gross_margin","relation":"higher_than","metricB":"gross_margin"}],
    "asset_type":["Common Stock"],"limit":15})],  # placeholder, replaced below
 "fe-08":[("screen_unified",{
    "fundamental":[
      {"concept":"roic","pattern":"sustained_above","threshold":0.15,"N":3},
      {"concept":"debt_to_equity","pattern":"below","threshold":0.5},
      {"concept":"current_ratio","pattern":"above","threshold":2.0}],
    "country":["CN","JP","IN","KR","TW","HK","SG","TH","MY","ID","PH","VN"],
    "asset_type":["Common Stock"],"limit":15})],
 "fe-09":[("screen_unified",{
    "fundamental":[
      {"concept":"revenue","pattern":"above","threshold":10000000000},
      {"concept":"rnd","pattern":"above","threshold":2000000000},
      {"metricA":"rnd","relation":"higher_than","metricB":"revenue","multiple":0.15}],
    "asset_type":["Common Stock"],"limit":15})],
 "fe-10":[("screen_unified",{
    "fundamental":[
      {"concept":"revenue","pattern":"compound_growth","threshold":0.20,"N":3},
      {"concept":"eps_diluted","pattern":"compound_growth","threshold":0.25,"N":3},
      {"concept":"roe","pattern":"sustained_above","threshold":0.20,"N":3},
      {"concept":"net_debt_ebitda","pattern":"below","threshold":2.0}],
    "asset_type":["Common Stock"],"limit":15})],
}


async def call_tool(s, tool, args):
    res = await s.call_tool(tool, args, read_timeout_seconds=datetime.timedelta(seconds=115))
    txt = "\n".join(getattr(c, "text", str(c)) for c in res.content)
    try:
        parsed = json.loads(txt)
    except Exception:
        parsed = {"_raw_text": txt}
    return {"isError": bool(res.isError), "parsed": parsed}


async def main():
    async with streamablehttp_client(URL, headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for cid in ["fe-01","fe-02","fe-03","fe-04","fe-05","fe-06","fe-07","fe-08","fe-09","fe-10"]:
                tools_called=[]; raw=[]
                plan = list(PLAN[cid])
                # fe-07: relation form higher_than needs metricA==metricB won't differentiate 'now vs 3y ago'.
                # Use consecutive_growth over 3y on all three margins (each expanding = up over the window).
                if cid=="fe-07":
                    plan=[("screen_unified",{
                       "fundamental":[
                          {"concept":"gross_margin","pattern":"consecutive_growth","N":3},
                          {"concept":"operating_margin","pattern":"consecutive_growth","N":3},
                          {"concept":"net_margin","pattern":"consecutive_growth","N":3}],
                       "asset_type":["Common Stock"],"limit":15})]
                for (tool,args) in plan:
                    tools_called.append({"tool":tool,"args":args})
                    out = await call_tool(s, tool, args)
                    raw.append(out["parsed"])
                # fe-03 second stage: financials compare with resolved tickers
                if cid=="fe-03":
                    # extract best ticker from each find_stock
                    tickers=[]
                    for block in raw:
                        t=None
                        cands = block.get("candidates") or block.get("results") or []
                        if isinstance(cands,list) and cands:
                            first=cands[0]
                            t=first.get("ticker") or first.get("symbol")
                        if not t and isinstance(block.get("ticker"),str):
                            t=block["ticker"]
                        tickers.append(t)
                    tickers=[t for t in tickers if t]
                    fin_args={"tickers":tickers,"period":"1","currency":"USD"}
                    tools_called.append({"tool":"financials","args":fin_args})
                    out=await call_tool(s,"financials",fin_args)
                    raw.append(out["parsed"])
                rec={"id":cid,"question":QUESTIONS[cid],
                     "tools_called":tools_called,"raw_responses":raw,"answer_to_user":""}
                json.dump(rec, open(f"{RAW}/{cid}.json","w"), ensure_ascii=False, indent=2)
                # stdout summary
                names="+".join(sorted(set(t["tool"] for t in tools_called)))
                last=raw[-1]
                cnt = last.get("count") if isinstance(last,dict) else None
                err = None
                for rr in raw:
                    if isinstance(rr,dict) and (rr.get("error") or rr.get("detail")):
                        err = rr.get("error") or rr.get("detail")
                print(f"{cid} | tools={names} | count/err={cnt if cnt is not None else err} | saved")


if __name__=="__main__":
    asyncio.run(main())
