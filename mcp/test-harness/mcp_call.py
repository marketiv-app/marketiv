#!/usr/bin/env python
"""Rock-solid MCP client CLI over the PINNED SDK — the transport a dumb-client subagent uses so it never
fights deps. Speaks real MCP JSON-RPC (streamable-http) to a running server.py; NOT a curl of /v1/*.

ALWAYS invoke through the pinned wrapper (matches serve-mcp.sh):
  uv run --no-project --python 3.12 --with 'mcp<2',httpx python mcp_call.py <cmd> ...

Env:  MCP_URL (default http://127.0.0.1:8901/mcp)   BEARER (avn_live_… key)
Commands:
  list                          → list every tool: name + one-line summary
  schema <tool>                 → full JSON input schema of ONE tool (so the client sees exact field names)
  call <tool> '<json-args>'     → invoke a tool; prints the JSON result
"""
import os, sys, json, asyncio, contextlib
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8901/mcp")
BEARER = os.environ.get("BEARER", "")
HEADERS = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}


async def _run(cmd, args):
    async with streamablehttp_client(URL, headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if cmd == "list":
                tools = (await s.list_tools()).tools
                for t in tools:
                    summ = (t.description or "").strip().splitlines()[0][:110]
                    print(f"{t.name:24s} {summ}")
            elif cmd == "schema":
                tools = {t.name: t for t in (await s.list_tools()).tools}
                t = tools.get(args[0])
                if not t: sys.exit(f"no such tool: {args[0]}")
                print(json.dumps(t.inputSchema, indent=2))
            elif cmd == "call":
                tool = args[0]
                payload = json.loads(args[1]) if len(args) > 1 else {}
                res = await s.call_tool(tool, payload)
                out = []
                for c in res.content:
                    out.append(getattr(c, "text", str(c)))
                print("\n".join(out))
                if res.isError:
                    sys.exit(2)
            else:
                sys.exit(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(sys.argv[1], sys.argv[2:]))
