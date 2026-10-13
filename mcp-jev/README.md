# marketiv-mcp — MCP server

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives your AI agent the
[Ava Advisor](https://ava.fund) financial **impact graph** as tools — ask *"which private AI
companies did this week's news move, and why?"* and the agent queries the graph directly (stocks,
commodities, FX, crypto, **and private companies**).

> Status: **beta** — 33 tools live over both stdio and hosted HTTP, with OAuth (Claude web "Connect"). Design + rationale live in the Ava repo
> `docs/product/mcp-server-design.md`. Explore the shape via the
> [sample dataset](../datasets/) and the [live playground](https://ava.fund/playground).

## Use it — hosted (no install)
The server is hosted at **`https://mcp.ava.fund/mcp`** (Streamable HTTP). Auth is **per-request**:
you send YOUR Ava Advisor key as a Bearer header — metered on your account, never a shared key. Get a key
at [ava.fund](https://ava.fund).

```bash
# Claude Code
claude mcp add --transport http marketiv \
  --header "Authorization: Bearer avn_live_…" \
  https://mcp.ava.fund/mcp
```
```jsonc
// Cursor — ~/.cursor/mcp.json  (any client that supports a remote MCP URL + headers)
{ "mcpServers": { "marketiv": {
    "url": "https://mcp.ava.fund/mcp",
    "headers": { "Authorization": "Bearer avn_live_…" } } } }
```
> Claude web / Desktop **Custom Connectors** use OAuth (a "Connect" button, no key to paste) — landing
> soon; until then use a client that allows a Bearer header, or run locally (below).

## Use it — local (stdio)
```bash
pip install marketiv-mcp            # or: uvx marketiv-mcp
export MARKETIV_API_KEY=avn_live_…    # https://ava.fund  (metered — your key, your credits)
export DEEPSEEK_API_KEY=…             # only for the composite tools (server-side LLM)
marketiv-mcp                           # stdio server — point your MCP config at this command
```

## Tools
Every tool takes plain names and concepts — a company name in any language, "semiconductors", "copper ore",
"core inflation", "grew every quarter" — and **resolves them server-side** (vector shortlist + a decision model),
so a client never needs a separate lookup round-trip. An ambiguous input comes back as `needs_confirmation`
with candidates.

- **One-call reads:** `pulse(kind=asset|theme|commodity|bond|macro|portfolio, target=…)` — every lens for the
  subject in one call (price, news→impact, options / futures positioning, fundamentals, peers).
- **News & impact:** `search_news` · `news_feed` · `stock_impact` · `brief` · `theme_summary` · `theme_players` ·
  `private_movers` · `relationships` · `list_themes`.
- **Prices & positioning:** `stock_prices` · `stock_prices_batch` · `options_sentiment` · `options_scan` ·
  `positioning` · `cot_extremes`.
- **Fundamentals & screening:** `financials` · `screen_unified` (fundamental × technical × options × universe) ·
  `screen_stocks` · `screen_dividends`.
- **Macro & trade:** `fred_series` · `wb_series` · `trade(mode=flows|top_partners|top_traders|balance)`.
- **The user's own data:** `list_portfolios` · `portfolio_context` · notes (`write_note`, `query_notes`,
  `get_note`) · playlists (`list_playlists`, `create_playlist`, `add_to_playlist`, `remove_from_playlist`).
- `suggest_cta(theme)` — data-backed "explore further" hooks into the graph.

## Resources
`avaadvisor://policy` — the gate/framing policy (skill.md) the client LLM should follow (honest scope,
5 response stances, no fudge). · `avaadvisor://capabilities` — live coverage/enums so the client scopes
correctly (expand "Asia" → the covered set; never request uncovered markets as if we had them).

## Architecture (why some tools are server-side)
The client's LLM (Claude / GPT / Gemini — the user's choice, we don't control it) handles single-pass
reasoning (which tool, final wording) guided by `avaadvisor://policy`. Correctness (coverage / dedup /
resolution) is deterministic in the API. Multi-step pipelines that would otherwise be many client↔server
roundtrips — resolving a concept to a code/ticker, fanning a pulse out across lenses — run server-side in **one**
call. Full split in the design doc.

