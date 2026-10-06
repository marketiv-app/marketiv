# marketiv-mcp — MCP server

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives your AI agent the
[MarketIV](https://marketiv.app) financial **impact graph** as tools — ask *"which private AI
companies did this week's news move, and why?"* and the agent queries the graph directly (stocks,
commodities, FX, crypto, **and private companies**).

> Status: **beta** — all 10 tools (simple + composite) live over both stdio and hosted HTTP; OAuth
> (Claude web "Connect") is next. Design + rationale live in the Ava repo
> `docs/product/mcp-server-design.md`. Explore the shape via the
> [sample dataset](../datasets/) and the [live playground](https://marketiv.app/playground).

## Use it — hosted (no install)
The server is hosted at **`https://mcp.marketiv.app/mcp`** (Streamable HTTP). Auth is **per-request**:
you send YOUR MarketIV key as a Bearer header — metered on your account, never a shared key. Get a key
at [marketiv.app](https://marketiv.app).

```bash
# Claude Code
claude mcp add --transport http marketiv \
  --header "Authorization: Bearer avn_live_…" \
  https://mcp.marketiv.app/mcp
```
```jsonc
// Cursor — ~/.cursor/mcp.json  (any client that supports a remote MCP URL + headers)
{ "mcpServers": { "marketiv": {
    "url": "https://mcp.marketiv.app/mcp",
    "headers": { "Authorization": "Bearer avn_live_…" } } } }
```
> Claude web / Desktop **Custom Connectors** use OAuth (a "Connect" button, no key to paste) — landing
> soon; until then use a client that allows a Bearer header, or run locally (below).

## Use it — local (stdio)
```bash
pip install marketiv-mcp            # or: uvx marketiv-mcp
export MARKETIV_API_KEY=avn_live_…    # https://marketiv.app  (metered — your key, your credits)
export DEEPSEEK_API_KEY=…             # only for the composite tools (server-side LLM)
marketiv-mcp                           # stdio server — point your MCP config at this command
```

## Tools
**Simple** (thin SDK wrappers — your client's LLM orchestrates):
`theme_summary` · `search_news` · `stock_impact` · `theme_players` · `private_movers` ·
`relationships` · `list_themes`.

**Composite** (whole multi-step pipeline runs server-side, one call):
`resolve_themes(terms)` — map trend-language ("HBM","foundry","cancer drug") to the right taxonomy
node(s). · `suggest_cta(theme)` — data-backed "explore further" hooks into the graph's moat.

## Resources
`marketiv://policy` — the gate/framing policy (skill.md) the client LLM should follow (honest scope,
5 response stances, no fudge). · `marketiv://capabilities` — live coverage/enums so the client scopes
correctly (expand "Asia" → the covered set; never request uncovered markets as if we had them).

## Architecture (why some tools are server-side)
The client's LLM (Claude / GPT / Gemini — the user's choice, we don't control it) handles single-pass
reasoning (which tool, final wording) guided by `marketiv://policy`. Correctness (coverage / dedup /
resolution) is deterministic in the API. Multi-step pipelines that would otherwise be many client↔server
roundtrips (`resolve_themes`, `suggest_cta`) are encapsulated as **one** composite tool running our own
cheap LLM (deepseek-v4-flash). Full split in the design doc.

⭐ **Star / watch** to hear when it ships.
