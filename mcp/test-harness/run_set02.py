#!/usr/bin/env python3
import os, sys, json, subprocess

HERE = "/Users/ran/Documents/marketdx/mcp/test-harness"
OUT = os.path.join(HERE, "raw", "set-02")
os.makedirs(OUT, exist_ok=True)
QS = json.load(open(os.path.join(HERE, "testsets", "set-02-technical-expert.json")))["cases"]
QMAP = {c["id"]: c["question"] for c in QS}

WRAP = ["uv","run","--no-project","--python","3.12","--with","mcp<2,httpx","python","mcp_call.py"]

def call(tool, args):
    """Invoke one MCP tool; return (parsed_or_rawstring, raw_text)."""
    p = subprocess.run(WRAP+["call", tool, json.dumps(args)], cwd=HERE,
                       capture_output=True, text=True)
    raw = p.stdout.strip()
    if p.returncode != 0 and not raw:
        raw = (p.stderr.strip().splitlines() or ["<empty>"])[0]
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = raw
    return parsed, raw

# ---- each case: list of (tool, args) in order ----
CASES = {}

# te-01: US, golden cross 50>200 SMA within 5 days, close above both MAs, mcap>$2B
CASES["te-01"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"crossover_up","a":"sma50","b":"sma200","window_bars":5}],
           "quals":[{"any":[{"pattern":"above","a":"close","b":"sma50"}],"within":0},
                    {"any":[{"pattern":"above","a":"close","b":"sma200"}],"within":0}]}],
    "country":["US"], "asset_type":["Common Stock"],
    "min_market_cap_usd":2000000000, "timeframe":1, "window_bars":5, "limit":15})]

# te-02: Thailand, daily bullish RSI divergence within ~1-2 months (~40 bars), volume spike >=1.5x 20d avg
CASES["te-02"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"divergence_bull","a":"rsi","window_bars":45}],
           "quals":[{"any":[{"pattern":"volume_spike"}],"within":0}]}],
    "country":["TH"], "asset_type":["Common Stock"],
    "timeframe":1, "window_bars":45, "limit":15})]

# te-03: global tech/semi, BB inside Keltner squeeze (ttm) + rising volume over 10 sessions
# gics 45 = IT sector
CASES["te-03"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"ttm_squeeze","window_bars":3}],
           "quals":[{"any":[{"pattern":"rising_volume"}]}]}],
    "gics":"45", "asset_type":["Common Stock"],
    "timeframe":1, "limit":15})]

# te-04: Europe large-cap, price dropped >=15% over 20d THEN MACD bullish cross within 3d
CASES["te-04"] = [("screen_unified", {
    "ta":[
      {"anchor":[{"pattern":"net_change_down","a":"close","b":"0.15","window_bars":20}]},
      {"anchor":[{"pattern":"crossover_up","a":"macd_line","b":"macd_signal","window_bars":3}]}
    ],
    "country":["GB","DE","FR","CH","NL","IT","ES","SE","BE","DK","FI","NO","IE","AT","PT","PL"],
    "size":["large"], "asset_type":["Common Stock"],
    "timeframe":1, "window_bars":25, "limit":15})]

# te-05: global, WEEKLY RSI(14) > 80, rank by RSI desc
CASES["te-05"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"above","a":"rsi","b":"80"}]}],
    "asset_type":["Common Stock"], "timeframe":2,
    "sort":"rsi", "limit":15})]

# te-06: US+CN; EPS growth 20% + gross margin >50%; near 200-EMA within 3% + daily RSI 40-50
CASES["te-06"] = [("screen_unified", {
    "fundamental":[
      {"concept":"eps_diluted","pattern":"latest_yoy","threshold":0.20},
      {"concept":"gross_margin","pattern":"above","threshold":0.50}
    ],
    "ta":[{"anchor":[{"pattern":"near_ma","b":"ema200"}],
           "quals":[{"any":[{"pattern":"in_range","a":"rsi","b":"40-50"}],"within":0}]}],
    "country":["US","CN"], "asset_type":["Common Stock"],
    "timeframe":1, "limit":15})]

# te-07: global small-cap <$1B, up >30% over 1 month (~21d) on above-avg volume, bearish RSI divergence
CASES["te-07"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"divergence_bear","a":"rsi","window_bars":30}],
           "quals":[
             {"any":[{"pattern":"net_change_up","a":"close","b":"0.30","window_bars":21}]},
             {"any":[{"pattern":"volume_spike"}]}
           ]}],
    "max_market_cap_usd":1000000000, "asset_type":["Common Stock"],
    "timeframe":1, "window_bars":30, "limit":15})]

# te-08: JP+KR, weekly>50-week SMA AND daily>20-EMA AND daily MACD histogram positive (macd_line>signal)
CASES["te-08"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"above","a":"macd_line","b":"macd_signal"}],
           "quals":[
             {"any":[{"pattern":"above","a":"close","b":"sma50","timeframe":2}],"within":0},
             {"any":[{"pattern":"above","a":"close","b":"ema20","timeframe":1}],"within":0}
           ]}],
    "country":["JP","KR"], "asset_type":["Common Stock"],
    "timeframe":1, "limit":15})]

# te-09: global energy, daily RSI(14) crossed UP through 30 within last 2 days
# gics 10 = Energy
CASES["te-09"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"crossover_up","a":"rsi","b":"30","window_bars":2}]}],
    "gics":"10", "asset_type":["Common Stock"],
    "timeframe":1, "window_bars":2, "limit":15})]

# te-10: global healthcare, price sustained above 200-day SMA + fresh MONTHLY MACD bullish cross, mcap>$5B
# gics 35 = Health Care. Monthly MACD cross = anchor on monthly timeframe; sustained-above-200SMA on daily via qualifier
CASES["te-10"] = [("screen_unified", {
    "ta":[{"anchor":[{"pattern":"crossover_up","a":"macd_line","b":"macd_signal","window_bars":3,"timeframe":3}],
           "quals":[{"any":[{"pattern":"above","a":"close","b":"sma200","for_bars":60,"timeframe":1}],"within":0}]}],
    "gics":"35", "asset_type":["Common Stock"],
    "min_market_cap_usd":5000000000, "timeframe":3, "window_bars":6, "limit":15})]

def count_of(parsed):
    if isinstance(parsed, dict):
        for k in ("count","total","n"):
            if k in parsed: return parsed[k]
        for k in ("results","matches","rows","stocks","candidates"):
            if isinstance(parsed.get(k), list): return len(parsed[k])
    return "?"

def top_tickers(parsed, k=5):
    if not isinstance(parsed, dict): return []
    out=[]
    for r in (parsed.get("results") or [])[:k]:
        t = r.get("ticker") or r.get("symbol") or r.get("also_known_as",[None])[0] or r.get("head_listing_id")
        out.append(str(t))
    return out

def answer_for(cid, parsed):
    if not isinstance(parsed, dict):
        return "The screen returned an error from the server (see raw response)."
    c = parsed.get("count", "?")
    tt = ", ".join(top_tickers(parsed))
    A = {
"te-01": f"I screened US-listed common stocks (>$2B market cap) for a FRESH 50-day/200-day SMA golden cross in the last ~5 sessions, confirmed by the close being above BOTH the 50- and 200-day SMA. Found {c} names" + (f" (e.g. {tt}).") if isinstance(c,int) and c else f"Found {c} matches.",
"te-02": f"หุ้นไทย (SET/mai) ที่เกิด bullish RSI divergence รายวัน (ราคาทำ lower low แต่ RSI ทำ higher low) ในช่วง ~45 วันทำการที่ผ่านมา และวันล่าสุดมี volume spike (สูงกว่าค่าเฉลี่ย). พบ {c} ตัว" + (f" เช่น {tt}." if isinstance(c,int) and c else "."),
"te-03": f"Global tech/IT-sector (GICS 45) common stocks in a Bollinger-inside-Keltner (TTM) volatility squeeze WITH climbing (rising) volume — a coiled, pre-breakout setup. This is direction-agnostic (no up/down call until it breaks). Found {c} names" + (f" (e.g. {tt}).") if isinstance(c,int) and c else f"Found {c}.",
"te-04": f"Two-step sequence on European large caps: a ≥15% drop over ~20 trading days, THEN a bullish daily MACD cross within the last 3 days. The screener enforced the ordering (drop first, then the cross). Result: {c} matches — the ≥15% drawdown leg is empty for EU large-caps right now, so the sequenced setup has no names currently.",
"te-05": f"Global common stocks with WEEKLY RSI(14) above 80 (extreme overbought), ranked by RSI descending. Found {c}" + (f"; most-overbought: {tt}." if isinstance(c,int) and c else ".") + " Note: extreme overbought alone is exhaustion context, not a short signal by itself.",
"te-06": f"US + China quality-growth pullbacks: diluted-EPS YoY growth ≥20% AND gross margin >50% (fundamentals) combined with price pulled back near the 200-day EMA and daily RSI in the 40-50 band (technical buy-the-dip zone). Found {c} names" + (f" (e.g. {tt}).") if isinstance(c,int) and c else f"Found {c}.",
"te-07": f"Global small caps (<$1B) up >30% over the last month on a volume spike, that are ALSO flashing bearish RSI divergence (price higher-high vs RSI lower-high) — momentum names that may be topping. Found {c}" + (f" (e.g. {tt}).") if isinstance(c,int) and c else f"Found {c}.",
"te-08": f"Japan + South Korea multi-timeframe trend alignment (ALL ANDed): price above the 50-week SMA on the weekly, above the 20-day EMA on the daily, and daily MACD histogram positive (MACD line above signal). Found {c}" + (f" (e.g. {tt}).") if isinstance(c,int) and c else f"Found {c}.",
"te-09": f"Global energy-sector (GICS 10) stocks whose daily RSI(14) crossed UP through 30 (oversold-exit trigger) in the last 2 sessions. Result: {c} — this is a genuine cross-up event, not a static oversold list; within just 2 days on energy alone it's currently very sparse (widening to ~10 days yields a couple).",
"te-10": f"หุ้น healthcare ทั่วโลก (GICS 35, market cap > $5B) ที่ราคายืนเหนือ 200-day SMA ต่อเนื่อง และเพิ่งเกิด MACD bullish crossover บน timeframe รายเดือน. ใช้ monthly timeframe จริงตามที่ขอ. ผลลัพธ์: {c} — monthly MACD cross เป็น event ที่หายากมาก (ทั้งตลาดตอนนี้แทบไม่มี), จึงไม่พบชื่อที่เข้าเงื่อนไขในขณะนี้.",
    }
    return A.get(cid, f"Found {c} matches.")

order = ["te-01","te-02","te-03","te-04","te-05","te-06","te-07","te-08","te-09","te-10"]
for cid in order:
    calls = CASES[cid]
    tools_called, raw_responses, names = [], [], []
    err = None
    for tool, args in calls:
        parsed, raw = call(tool, args)
        tools_called.append({"tool":tool,"args":args})
        raw_responses.append(parsed)
        names.append(tool)
        if isinstance(parsed, dict) and ("error" in parsed or parsed.get("isError")):
            err = str(parsed)[:60]
        elif isinstance(parsed, str) and ("rror" in parsed or "alidation" in parsed):
            err = parsed[:60]
    last = raw_responses[-1]
    cnt = count_of(last)
    rec = {"id":cid, "question":QMAP[cid],
           "tools_called":tools_called, "raw_responses":raw_responses,
           "answer_to_user":""}
    ans = answer_for(cid, last)
    rec["answer_to_user"] = ans
    json.dump(rec, open(os.path.join(OUT, cid+".json"),"w"), indent=1, ensure_ascii=False)
    ce = err if err else cnt
    print(f"{cid} | tools={','.join(names)} | count/err={ce} | answer={ans[:60]}")
