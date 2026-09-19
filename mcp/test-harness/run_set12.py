#!/usr/bin/env python
"""Run set-12-multi-asset test cases via real MCP protocol."""
import os, sys, json, asyncio, contextlib
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
import datetime as dt

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8901/mcp")
BEARER = os.environ.get("BEARER", "")
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}
OUT = Path("/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-12-run1")
OUT.mkdir(parents=True, exist_ok=True)


async def call_tool(s, tool, payload):
    res = await s.call_tool(tool, payload, read_timeout_seconds=dt.timedelta(seconds=115))
    texts = [getattr(c, "text", str(c)) for c in res.content]
    text = "\n".join(texts)
    try:
        return json.loads(text), res.isError
    except:
        return text, res.isError


async def main():
    async with streamablehttp_client(URL, headers=HEADERS,
                                     timeout=dt.timedelta(seconds=120),
                                     sse_read_timeout=dt.timedelta(seconds=120)) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()

            # Hardcoded ta_steps using confirmed anchor format from set-01
            CASE_TA = {
                "ma-01": [{"anchor": [{"pattern": "overbought"}]}],
                "ma-02": [{"anchor": [{"pattern": "crossover_up", "a": "macd_line", "b": "macd_signal"}]}],
                "ma-03": [{"anchor": [{"pattern": "near_high"}]}],
                "ma-04": [{"anchor": [{"pattern": "crossover_up", "a": "ema50", "b": "ema200"}]}],
                "ma-05": [{"anchor": [{"pattern": "oversold"}]}],
                "ma-06": [{"anchor": [{"pattern": "bb_squeeze", "window_bars": 5}]}],
                "ma-07": [{"anchor": [{"pattern": "crossover_down", "a": "ema50", "b": "ema200"}]}],
                "ma-08": [{"anchor": [{"pattern": "at_new_high"}]}],
                "ma-09": [{"anchor": [{"pattern": "crossover_up", "a": "close", "b": "ema20"}]}],
                "ma-10": [{"anchor": [{"pattern": "net_change_up", "b": "0.05", "window_bars": 22}]}],
            }

            questions = {
                "ma-01": "What assets across all markets — stocks, crypto, forex — are showing RSI above 70 right now?",
                "ma-02": "Which cryptocurrencies just had a bullish MACD crossover?",
                "ma-03": "Show me forex pairs that are near a 52-week high right now.",
                "ma-04": "Are there any assets — doesn't matter if it's stocks, crypto, or forex — that just had a golden cross?",
                "ma-05": "What crypto is really oversold right now — RSI below 30?",
                "ma-06": "I want to find assets across all markets that have been quietly consolidating — low volatility squeeze.",
                "ma-07": "Which forex pairs are showing a death cross — 50-day MA crossing below the 200-day?",
                "ma-08": "Show me the top crypto tokens that are at a 52-week high right now.",
                "ma-09": "Show me everything — stocks AND crypto AND forex — that just broke out above their 20-day moving average.",
                "ma-10": "Give me a picture of momentum across all markets — what asset types are strongest right now?",
            }

            # (id, asset_type_list_or_none)
            cases = [
                ("ma-01", None),
                ("ma-02", ["Crypto"]),
                ("ma-03", ["Currency"]),
                ("ma-04", None),
                ("ma-05", ["Crypto"]),
                ("ma-06", None),
                ("ma-07", ["Currency"]),
                ("ma-08", ["Crypto"]),
                ("ma-09", None),
                ("ma-10", None),
            ]

            for case_id, asset_types in cases:
                print(f"\n--- {case_id} ---")
                ta_steps = CASE_TA[case_id]
                args = {"ta": ta_steps, "limit": 20}
                if asset_types:
                    args["asset_type"] = asset_types

                print(f"  Calling screen_unified: asset_type={asset_types}, ta={ta_steps}")
                data, err = await call_tool(s, "screen_unified", args)

                if err or isinstance(data, str):
                    summary = f"error: {str(data)[:200]}"
                    verdict = "FAIL"
                    reason = "screen_unified returned error"
                    defects = [{"desc": summary[:100], "side": "ta-backend"}]
                else:
                    count = data.get("count", 0)
                    results = data.get("results", [])
                    asset_type_set = list(set(r.get("asset_type", "") for r in results[:10]))
                    top = [r.get("ticker", "") for r in results[:5]]
                    summary = f"count={count}, types={asset_type_set}, top={top}"
                    print(f"  Result: {summary}")

                    # Judge
                    if asset_types == ["Crypto"]:
                        has_crypto = any("Crypto" in r.get("asset_type", "") or ".CC" in r.get("ticker", "") for r in results[:10])
                        verdict = "PASS" if count > 0 and has_crypto else ("PARTIAL" if count > 0 else "FAIL")
                        reason = "crypto results returned" if has_crypto else "no crypto in results"
                        defects = [] if has_crypto else [{"desc": "Expected crypto assets, got mixed or none", "side": "data-coverage"}]
                    elif asset_types == ["Currency"]:
                        has_forex = any("Currency" in r.get("asset_type", "") or ".FOREX" in r.get("ticker", "") for r in results[:10])
                        verdict = "PASS" if count > 0 and has_forex else ("PARTIAL" if count > 0 else "FAIL")
                        reason = "forex results returned" if has_forex else "no forex in results"
                        defects = [] if has_forex else [{"desc": "Expected forex (Currency) assets, got mixed or none", "side": "data-coverage"}]
                    else:
                        # All assets: expect multiple types
                        n_types = len(set(r.get("asset_type", "") for r in results))
                        verdict = "PASS" if count > 0 and n_types >= 2 else ("PARTIAL" if count > 0 else "FAIL")
                        reason = f"{n_types} asset type(s) in results" + ("" if n_types >= 2 else " — expected multi-asset")
                        defects = [] if n_types >= 2 else [{"desc": "Expected multiple asset types in broad screen", "side": "mcp-guidance"}]

                tool_calls = [{"tool": "screen_unified", "args": args}]
                result = {
                    "id": case_id,
                    "question": questions[case_id],
                    "tool_calls": tool_calls,
                    "result_summary": summary,
                    "verdict": verdict,
                    "reason": reason,
                    "defects": defects,
                }
                (OUT / f"{case_id}.json").write_text(json.dumps(result, indent=2))
                print(f"  Verdict: {verdict} — {reason}")

    print("\nDone. Results in:", OUT)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
