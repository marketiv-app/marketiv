#!/usr/bin/env python
"""Driver for set-03 fundamental-novice. Speaks MCP via the pinned SDK, saves full raw responses."""
import os, sys, json, asyncio, datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8901/mcp")
BEARER = os.environ.get("BEARER", "")
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}
OUT = "/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-03"
os.makedirs(OUT, exist_ok=True)


async def call(s, tool, args):
    try:
        res = await s.call_tool(tool, args, read_timeout_seconds=datetime.timedelta(seconds=115))
        texts = []
        for c in res.content:
            t = getattr(c, "text", None)
            if t is None:
                texts.append({"_nontext": str(c)})
            else:
                try:
                    texts.append(json.loads(t))
                except Exception:
                    texts.append(t)
        payload = texts[0] if len(texts) == 1 else texts
        return {"isError": bool(res.isError), "result": payload}
    except Exception as e:
        return {"isError": True, "result": {"_exception": f"{type(e).__name__}: {e}"}}


def save(case):
    with open(f"{OUT}/{case['id']}.json", "w") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)
    tools = ",".join(t["tool"] for t in case["tools_called"])
    # count/err summary
    summ = []
    for rr in case["raw_responses"]:
        r = rr.get("result", {})
        if isinstance(r, dict) and "count" in r:
            summ.append(f"count={r['count']}")
        elif isinstance(r, dict) and r.get("_exception"):
            summ.append("EXC")
        elif rr.get("isError"):
            summ.append("ERR")
        else:
            summ.append("ok")
    ans = case["answer_to_user"][:60].replace("\n", " ")
    print(f"{case['id']} | tools={tools} | {'/'.join(summ)} | answer={ans}")


async def main():
    async with streamablehttp_client(URL, headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()

            # Build plan: (id, question, [ (tool,args), ... ], answer_fn or answer text)
            # We run tools, collect raw, then compose answer referencing raw.
            for spec in PLAN:
                cid = spec["id"]
                calls = spec["calls"]
                raws = []
                tcalled = []
                for (tool, args) in calls:
                    tcalled.append({"tool": tool, "args": args})
                    raws.append(await call(s, tool, args))
                answer = spec["answer"](raws)
                case = {
                    "id": cid,
                    "question": spec["question"],
                    "tools_called": tcalled,
                    "raw_responses": [rr["result"] for rr in raws],
                    "answer_to_user": answer,
                }
                # attach error flags into raw if present already in result
                save(case)


# ---- helpers for answer composition ----
def rows(raw):
    r = raw["result"]
    if isinstance(r, dict):
        return r.get("results") or []
    return []


def names(raw, n=6):
    out = []
    for x in rows(raw)[:n]:
        nm = x.get("name") or x.get("ticker")
        tk = x.get("ticker", "")
        out.append(f"{nm} ({tk})")
    return out


PLAN = []
