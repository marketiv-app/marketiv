#!/usr/bin/env python
"""Set-05 combined TA+fundamental dumb-client runner.
Speaks MCP via mcp_call.py's session logic. Saves full raw responses to raw/set-05/<id>.json.
Invoke with the pinned wrapper:
  uv run --no-project --python 3.12 --with 'mcp<2',httpx python run_set05.py
"""
import os, sys, json, asyncio, datetime, pathlib
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8901/mcp")
BEARER = os.environ.get("BEARER", "")
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}
OUT = pathlib.Path("/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-05")
OUT.mkdir(parents=True, exist_ok=True)

# Asia ISO-2 for cf-05 (tech in Asia)
ASIA = ["CN","JP","KR","TW","HK","IN","SG","TH","MY","ID","PH","VN"]

# Each case: id, question, list of screen_unified args (usually 1)
CASES = [
  {
    "id":"cf-01",
    "question":"Find me profitable companies with revenue growing over 20% a year that just broke out above their 50-day moving average.",
    "args":{
      "fundamental":[
        {"concept":"net_income","pattern":"is_positive"},
        {"concept":"revenue","pattern":"compound_growth","threshold":0.20}
      ],
      "ta":[{"anchor":[{"pattern":"crossover_up","a":"close","b":"ema50"}]}],
      "asset_type":["Common Stock"],
      "timeframe":1,"window_bars":20,"limit":10
    }
  },
  {
    "id":"cf-02",
    "question":"I want cheap stocks — low P/E, under 15 — that are still trading above their 200-day moving average. US large caps only.",
    "args":{
      "fundamental":[{"concept":"pe","pattern":"below","threshold":15}],
      "ta":[{"anchor":[{"pattern":"above","a":"close","b":"ema200"}]}],
      "country":["US"],"size":["large"],"asset_type":["Common Stock"],
      "timeframe":1,"window_bars":0,"limit":10
    }
  },
  {
    "id":"cf-03",
    "question":"Show me high-margin, low-debt companies that have sold off hard recently and are now oversold — RSI below 30.",
    "args":{
      "fundamental":[
        {"concept":"net_margin","pattern":"high"},
        {"concept":"debt_to_equity","pattern":"low"}
      ],
      "ta":[{"anchor":[{"pattern":"oversold","a":"rsi"}]}],
      "asset_type":["Common Stock"],
      "timeframe":1,"window_bars":20,"limit":10
    }
  },
  {
    "id":"cf-04",
    "question":"หาหุ้นปันผลดี ยิลด์เกิน 4% ที่ราคายังอยู่ในเทรนด์ขาขึ้น อยู่เหนือเส้นค่าเฉลี่ย 200 วัน",
    "args":{
      "fundamental":[{"concept":"dividend_yield","pattern":"above","threshold":0.04}],
      "ta":[{"anchor":[{"pattern":"above","a":"close","b":"ema200"}]}],
      "asset_type":["Common Stock"],
      "timeframe":1,"window_bars":0,"limit":10
    }
  },
  {
    "id":"cf-05",
    "question":"Give me quality tech companies in Asia — return on equity above 15% — where the stock dropped more than 25% from its 52-week high but the business is still growing revenue.",
    "args":{
      "fundamental":[
        {"concept":"roe","pattern":"above","threshold":0.15},
        {"concept":"revenue","pattern":"compound_growth","threshold":0.0}
      ],
      "ta":[{"anchor":[{"pattern":"off_high_by","b":"0.25"}]}],
      "gics":"45","country":ASIA,"asset_type":["Common Stock"],
      "timeframe":1,"window_bars":10,"limit":10
    }
  },
  {
    "id":"cf-06",
    "question":"I'm looking for large-cap value stocks — high free cash flow yield — that are coming out of a long volatility squeeze and starting to move up.",
    "args":{
      "fundamental":[{"concept":"fcf_yield","pattern":"high"}],
      "ta":[{"anchor":[{"pattern":"squeeze_fired_up"}]}],
      "size":["large"],"asset_type":["Common Stock"],
      "timeframe":1,"window_bars":20,"limit":10
    }
  },
  {
    "id":"cf-07",
    "question":"Find healthcare companies with over $1 billion in revenue and expanding margins that just made a bullish MACD crossover.",
    "args":{
      "fundamental":[
        {"concept":"revenue","pattern":"above","threshold":1000000000},
        {"concept":"net_margin","pattern":"improved_every_year","N":3}
      ],
      "ta":[{"anchor":[{"pattern":"crossover_up","a":"macd_line","b":"macd_signal"}]}],
      "gics":"35","asset_type":["Common Stock"],
      "timeframe":1,"window_bars":15,"limit":10
    }
  },
  {
    "id":"cf-08",
    "question":"หุ้นจีนตัวเล็กที่กำไรโต แต่ราคาลงมา 30% แล้ว และตอนนี้ RSI รีเซ็ตต่ำกว่า 40 มีตัวไหนบ้าง",
    "args":{
      "fundamental":[{"concept":"net_income","pattern":"compound_growth","threshold":0.0}],
      "ta":[{"anchor":[{"pattern":"off_high_by","b":"0.30"}],
             "quals":[{"any":[{"pattern":"in_range","a":"rsi","b":"0-40"}]}]}],
      "country":["CN"],"size":["small"],"asset_type":["Common Stock"],
      "timeframe":1,"window_bars":15,"limit":10
    }
  },
  {
    "id":"cf-09",
    "question":"Which dividend growers in Europe — raising their payout and yielding over 3% — recently reclaimed their 50-day moving average after a dip?",
    "args":{
      "fundamental":[
        {"concept":"dividend_yield","pattern":"above","threshold":0.03},
        {"concept":"dps","pattern":"improved_every_year","N":3}
      ],
      "ta":[{"anchor":[{"pattern":"crossover_up","a":"close","b":"ema50"}]}],
      "country":["GB","FR","DE","IT","ES","NL","SE","CH","BE","DK","FI","NO","AT","IE","PT"],
      "asset_type":["Common Stock"],
      "timeframe":1,"window_bars":20,"limit":10
    }
  },
  {
    "id":"cf-10",
    "question":"I want financially strong companies — growing earnings, low debt-to-equity — that are showing bullish divergence on the daily chart. Any sector, global.",
    "args":{
      "fundamental":[
        {"concept":"net_income","pattern":"compound_growth","threshold":0.0},
        {"concept":"debt_to_equity","pattern":"low"}
      ],
      "ta":[{"anchor":[{"pattern":"divergence_bull"}]}],
      "asset_type":["Common Stock"],
      "timeframe":1,"window_bars":50,"limit":10
    }
  },
]


def parse_result(res):
    texts=[]
    for c in res.content:
        t=getattr(c,"text",None)
        if t is None: t=str(c)
        texts.append(t)
    joined="\n".join(texts)
    try:
        return json.loads(joined)
    except Exception:
        return {"_raw_text":joined}


async def main():
    summary=[]
    async with streamablehttp_client(URL, headers=HEADERS) as (r,w,_):
        async with ClientSession(r,w) as s:
            await s.initialize()
            for case in CASES:
                tools_called=[]; raw=[]; err=None; count=None
                args=case["args"]
                tools_called.append({"tool":"screen_unified","args":args})
                try:
                    res=await s.call_tool("screen_unified", args, read_timeout_seconds=datetime.timedelta(seconds=115))
                    parsed=parse_result(res)
                    raw.append(parsed)
                    if res.isError:
                        err=parsed
                    else:
                        count=parsed.get("count", len(parsed.get("results",[])) if isinstance(parsed,dict) else None)
                except Exception as e:
                    err={"exception":str(e)}
                    raw.append(err)
                # build answer
                if err:
                    ans=f"[error] {json.dumps(err,ensure_ascii=False)[:200]}"
                else:
                    p=raw[0]; rows=p.get("results",[]) if isinstance(p,dict) else []
                    names=[row.get("ticker") or row.get("name") for row in rows[:8]]
                    ans=f"Found {count} matches. Top: {', '.join(str(n) for n in names)}"
                out={"id":case["id"],"question":case["question"],
                     "tools_called":tools_called,"raw_responses":raw,"answer_to_user":ans}
                (OUT/f"{case['id']}.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
                cnt = err and "ERR" or count
                summary.append(f"{case['id']} | tools=screen_unified | count/err={cnt} | answer={ans[:60]}")
    print("\n".join(summary))

if __name__=="__main__":
    asyncio.run(main())
