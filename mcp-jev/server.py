"""MarketDX MCP server — gives an AI agent the MarketDX financial-impact graph as tools.

Architecture (see docs/product/mcp-server-design.md in the Ava repo):
  • SIMPLE tools  → thin wrappers over the marketdx Python SDK (which calls the metered /v1 API).
                    The client's own LLM orchestrates these; correctness lives in the API/SDK.
  • COMPOSITE tools (theme_pulse, suggest_cta) → multi-step pipelines that would be N client↔server
                    roundtrips if offloaded, so they run WHOLLY server-side (a mix of the unified Jev
                    concept resolver + our own cheap LLM for the ETF/CTA-curation steps) in ONE call.
  • RESOLUTION    → an English industry/theme concept → GICS code(s) / megatrend node(s) is done SERVER-side
                    by the unified vector+Jev `_resolve_concept` (no client find_* round-trip; no gazetteer/
                    deepseek). Consumers pass plain English in `gics`/`megatrend`/`theme`; the server routes it.
  • RESOURCES     → the gate policy (skill.md) + a live capabilities/coverage map.

Run:  MARKETDX_API_KEY=avn_live_… DEEPSEEK_API_KEY=… uvx marketdx-mcp     (or `python server.py`)
Deps: mcp (FastMCP), marketdx, openai (deepseek is OpenAI-compatible).
"""
from __future__ import annotations
import os, re, json, pathlib, contextvars
from dataclasses import asdict, is_dataclass
from typing import Annotated, Any, Optional, List, Literal, Union
from pydantic import Field, AliasChoices, BaseModel, ConfigDict

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from marketdx import MarketDX, NotFoundError, MarketDXError

# DNS-rebinding protection defaults to a localhost allow-list (it guards a *local* server from
# browser-driven Host spoofing). We're a hosted API behind Cloud Run TLS with our own per-request
# Bearer auth, and the Host varies (run.app + mcp.marketdx.lab.ai) — so disable the Host check here.
# Server instructions — the client LLM reads this at connect time. Its main job: stop the client from
# web-searching topics MarketDX actually covers (esp. COMMODITIES/metals, which agents forget we have).
_INSTRUCTIONS = (
    "MarketDX is a financial news→impact graph: it maps news to the assets and megatrends it actually "
    "moves — direction (+/−), the reason WHY, and the ripple to connected players — across STOCKS, "
    "FOREX, CRYPTO, COMMODITIES (metals like copper & gold, energy like oil & gas, agris, carbon/EU-ETS "
    "allowances, and LME-vs-onshore-China metal variants), GOVERNMENT-BOND YIELDS, MONEY-MARKET RATES, and "
    "PRIVATE / off-coverage companies. For ANY question about news, market impact, or what moved an "
    "asset or theme — INCLUDING commodities and metals (copper, gold, oil, …) — use THESE tools, not a "
    "web search: MarketDX returns scored per-article impact + the causal 'why' + the ripple that a web "
    "search cannot. Commodities use a `SYMBOL.COMM` ticker (COPPER.COMM, GOLD.COMM, CARBON_EU.COMM, "
    "NICKEL_LME.COMM) with stock_impact, or just search_news('copper'); some metals have BOTH an "
    "onshore-China (CNY) and an LME (USD) contract, and palm oil a USD (PALMOIL) vs Bursa-MYR (PALMOIL_MY) "
    "variant. Government-bond YIELDS use `<ISO2>-<TENOR>.GB` (US-10Y.GB, JP-10Y.GB, DE-2Y.GB) and money-"
    "market RATES `<TOKEN>.MM` (SOFR.MM, EFFR.MM, EURIBOR3M.MM); a yield/rate MOVE reads in BASIS POINTS "
    "(`change_bps`), never as a % of the yield — and a yield has no options/PE/market-cap, so those lenses "
    "being absent for a `.GB`/`.MM` ticker is EXPECTED, not a failure. Just pass the name or ticker to "
    "asset_pulse/stock_prices — they resolve it server-side (US 10-year treasury→US-10Y.GB, SOFR→SOFR.MM). "
    "News tools accept a time range (`from_`/`to` ISO or `window` like "
    "'90d'/'qtd'/'1y'); to compare periods, call the tool once per period and compare. "
    "⚠️ NEWS coverage starts 2026-01-01 — there is NO news before 2026; for an older period say so "
    "plainly, never fabricate or present an empty result as 'nothing happened'. PRICE / volatility "
    "history, by contrast, goes back decades — so 'why was gold volatile in 2023' is answerable from "
    "price even though there's no 2023 news. Any read on how a tradable asset (a stock, ETF, or index) is "
    "DOING — whatever the phrasing or language — is a MarketDX question: our news→impact + options-"
    "positioning read IS the substance of 'how is it doing' (the WHY it's moving + the market's stance), "
    "which a web search cannot supply. Reach for `asset_pulse(<ticker>)` on these. 🔴 This INCLUDES a "
    "MARKET / INDEX asked in a 'right now / ตอนนี้ / current' phrasing (S&P, Nasdaq, Dow, 'the market'): "
    "map it to its ETF (S&P→SPY · Nasdaq→QQQ · Dow→DIA — WE DO COVER their options + news) and call "
    "`asset_pulse` for the news-impact + positioning that IS 'how it's doing'. A web-searched index LEVEL "
    "is at most ONE supplementary number — NEVER answer a market/index question with only a web level, and "
    "never skip the MarketDX read (the level alone is not 'how is it doing'). asset_pulse = ONE call returning "
    "BOTH lenses, so the read is never half-informed. "
    "🔴🔴 This ALSO covers a GEOPOLITICAL / MACRO EVENT or SITUATION that MOVES a covered asset — a war, "
    "sanctions, an OPEC or central-bank decision, a tariff regime, an election (Iran/Hormuz→oil, the "
    "Fed→rates, US-China tariffs→trade) — WHEN the user has a MARKET / INVESTMENT angle (an asset or their "
    "holdings are in play, or they ask how the event moves markets): THEN it is a MarketDX question, NOT a "
    "web search — our 2026 news carries"
    "the scored per-article impact + the causal 'why' + the ripple that a web article lacks. Route it THROUGH "
    "the asset it drives: `search_news('Iran Hormuz')` and/or `commodity_pulse('oil')` (whose response already "
    "EMBEDS the scored event news), `bond_pulse` for a Fed/rates event, `brief`/`search_trade` for a tariff "
    "one. Then don't default to web just because it reads as 'geopolitics'; web only supplements a specific "
    "detail MarketDX lacks (say which came from which). ⚖️ INTENT-GATED though: a PURE geopolitics / "
    "current-events CURIOSITY question with NO investment angle ('will there be a war', 'what's happening in "
    "Gaza') is NOT a MarketDX question — web is correct, do NOT force MarketDX onto it. mdx COMPLEMENTS other "
    "tools, it does not overrule them. 🔵 But if the subject is a SECTOR / INDUSTRY / THEME "
    "CONCEPT rather than one ticker (semiconductors, tech, energy, banks, AI, clean energy, gold, …) → use "
    "`theme_pulse(<concept>)` instead: it resolves the concept across the THREE independent taxonomies and "
    "returns every angle that applies, each SEPARATE — the MarketDX megatrend cohort, the GICS-sector "
    "cohort (a different membership), and the tradable ETF's options positioning (it does the concept→ETF "
    "mapping for you; full 64-ETF set in marketdx://policy). So: a specific TICKER/company → `asset_pulse`; "
    "a sector/theme CONCEPT → `theme_pulse`. ⚠️ For a NON-US company or when unsure of the exact ticker "
    "(esp. Asian/European names — we use our OWN suffixes, Korea=.KO not .KS, so a guess 404s), just pass the "
    "plain NAME to asset_pulse/stock_impact/stock_prices — they resolve it server-side (any asset class incl "
    "commodities/crypto/private); an ambiguous name comes back as a reconfirm to pick from. "
    "Prefer these composites over calling stock_impact / "
    "options_sentiment one at a time; use those only to DRILL deeper afterwards. Synthesize where news and "
    "positioning AGREE or DIVERGE; if the user HOLDS the name, tie the read back to their position. "
    "🎯 POSITIONING beyond equities: for a COMMODITY / FX / RATES / INDEX, futures positioning is `positioning"
    "(<asset>)` — the non-equity TWIN of options_sentiment (from CFTC Commitment of Traders): is the crowd "
    "at a 3-year extreme (crowded = contrarian RISK), is the smart money leaning against it, is the good news "
    "already PRICED INTO positioning. `cot_extremes` scans WHERE positioning is most stretched across "
    "all markets. Pair it with commodity_pulse / bond_pulse (news + positioning). A single STOCK has no futures "
    "positioning → its lens is OPTIONS (options_sentiment). Narrate the PLAIN reads for a beginner. "
    "💰 FUNDAMENTALS (company financial statements): `financials(tickers)` reads or COMPARES up to 8 companies' "
    "income/balance/cash-flow — revenue, growth, margins, FCF, and (US filers) EDGAR note-level quality-of-"
    "earnings (deferred revenue, stock comp, tax). Use it for an explicit financials / งบการเงิน ask, a "
    "fundamentals COMPARE ('which of these is more profitable', 'compare Apple vs TSMC vs Samsung'), or "
    "`full`/`period=quarterly` depth. Cross-currency compares convert to USD automatically (margins/growth are "
    "currency-neutral). EQUITY ONLY — an ETF/commodity/bond/crypto has no company financials. 🔴 But a plain "
    "'how is <stock> doing / น่าลงทุนไหม' does NOT need a separate financials call: `asset_pulse` on a stock "
    "ALREADY embeds the fundamentals summary (the `fundamentals` block) — read that; reach for `financials` "
    "only when they want a dedicated compare, quarterly, or full statements. Pass NAMES straight to these tools — "
    "they resolve names → tickers server-side. Narrate the PLAIN read for a beginner; translate any raw XBRL tag into everyday words. "
    "🧠 ANALYTICAL MINDSET — when the user asks you to ASSESS or read an OUTLOOK ('how's X', 'แนวโน้ม', "
    "'น่าสนใจไหม', 'should I worry', 'is it cheap') rather than a bare price/number: asset_pulse/theme_pulse "
    "is the CORE read, but it is NOT the whole answer. Before you conclude, ASK YOURSELF what OFF-INSTRUMENT "
    "backdrop would MATERIALLY change this read, and go GATHER it — do not answer from a single tool by "
    "reflex. Map the entity to its real drivers using your own world-knowledge: a DOMESTIC-demand business "
    "(a consumer/retail/bank/property/telecom name that sells mainly into ITS OWN country — e.g. CPALL, a "
    "local bank, a homebuilder) is driven by that COUNTRY'S STRUCTURAL health, so pull it with "
    "`wb_series` (pass a concept) for the stock's country (household consumption, HOUSEHOLD DEBT, GDP-per-"
    "capita growth, credit — the demand backdrop the price+news alone can't give); an EXPORTER / tariff- or "
    "supply-chain-exposed name → the TRADE flows (`search_trade`/`top_traders` — pass a product concept in `codes`); a rate- or "
    "macro-sensitive read → the macro series (`fred_series` — pass a concept, or `macro_pulse`). Pull ONLY the "
    "1–2 backdrops that would actually move the conclusion (cheap, high-signal — find_* resolvers are FREE), "
    "then SYNTHESIZE: does the structural/macro/trade backdrop CONFIRM or CONTRADICT the price+news? Never "
    "gather just to look thorough — but never leave a domestic-consumer, exporter, or macro-sensitive read "
    "backdrop-BLIND either (that is the difference between a data readout and an analyst's answer). The "
    "stock's country + sector (from asset_pulse / financials) is enough to know WHICH backdrop applies. "
    "To SUMMARIZE a whole scope — a news CATEGORY (e.g. "
    "'สรุปข่าว commodity' → news_type='commodity_supply'), a country/market, an impact channel (aspect), "
    "a GICS sector, a megatrend, or any AND-mix — use `brief` (the composed 'how is <X> doing right now?' "
    "picture), NOT search_news/news_feed (those return a raw article LIST, not a summary). A sector/trend term "
    "in `brief`/`theme_pulse` is resolved server-side; follow marketdx://policy for voice, scope, and stance. "
    "NOTES — the user keeps a personal INVESTMENT KNOWLEDGE BASE via `write_note` (their notes join this "
    "same graph and are retrievable by entity later — the point is to fight scattered knowledge). Act as a "
    "proactive librarian: after a SUBSTANTIVE investment answer — a sector/mechanism explainer, a dated "
    "market read (with its 'why'), a thesis, a comparison, a decision — briefly OFFER to keep it "
    "('เก็บเข้าโน้ตไหม?'), and save right away on any explicit 'save this / จดไว้'. When you save, pass the "
    "stocks + sector/theme this turn is about so the note links to the graph — `write_note` RESOLVES names "
    "server-side: put stock NAMES/tickers in `stocks`, and the sector/trend word(s) straight in `gics` (plain "
    "English is fine — a curated theme is routed to a megatrend automatically). 🔴 LIKEWISE a COMMODITY you "
    "discussed only via the TRADE tools or keyword news (`search_trade` etc. resolve a product concept to an HS code e.g. rice→1006, "
    "NOT a ticker) — just put the commodity NAME in `stocks` (rice→resolved to RICE.COMM, copper→COPPER.COMM) so "
    "the note links to it in the graph. (A stock chat "
    "usually resolved the ticker already; a commodity/trade chat often has NOT — this is the easy miss.) Do NOT offer on "
    "chit-chat, trivia lookups (e.g. 'what's NVDA's ticker'), or off-topic / non-investment turns; don't "
    "nag more than once, and never save pure filler."
)
mcp = FastMCP("marketdx", instructions=_INSTRUCTIONS, website_url="https://marketdx.lab.ai",
              # stateless_http + json_response: every request is fully self-contained (auth = per-request
              # Bearer key; no in-memory session pinned to an instance) and returns a plain JSON body (no
              # held-open SSE stream). Required for clean horizontal scaling — a stateful session breaks the
              # moment Cloud Run routes a follow-up request to a different instance ("Session not found").
              # Provenance that used to come from the session handshake now comes from write_note's `agent`.
              stateless_http=True,
              json_response=True,
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
_HERE = pathlib.Path(__file__).parent
# Served at /favicon.ico so clients (Claude's connector card) show the MarketDX mark for this host —
# without it, a favicon resolver strips the subdomain and grabs the apex lab.ai icon.
_FAVICON = (_HERE / "favicon.ico").read_bytes() if (_HERE / "favicon.ico").exists() else b""
# Every tool here is READ-ONLY (queries the graph / runs our own LLM — never writes user data). The
# readOnlyHint lets a client auto-run without a confirm prompt, and it's a Connector-Directory gate.
# Convention: give EVERY new tool a `title=` + `annotations=_RO` (or a destructive hint if it ever writes).
_RO = ToolAnnotations(readOnlyHint=True)
# WRITE tools persist user data → readOnlyHint=False so a client can prompt/confirm before running.
# additive (a new note), not an update/delete → not destructive, not idempotent.
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)

# ── Per-parameter descriptions (the AUTHORITATIVE layer — a tool must be precise ON ITS OWN, not lean on a
# skill). `_d(desc)` returns a FRESH pydantic Field per param (never share a FieldInfo across fields).
# Reusable strings keep the common params (window/limit/ticker/…) consistent across all 32 tools. ──
def _d(desc: str):  # noqa: ANN201
    return Field(description=desc)
# One consistent name for the free-text identifier across the whole tool family — canonical `q`.
# validation_alias makes the schema expose ONLY `q`, but silently ACCEPTS the names an LLM's prior
# tends to reach for (query/name/commodity/symbol/…), so the client never trips on the param NAME.
# Includes tool-name-derived tokens (theme_pulse→`theme`, bond_pulse→`bond`/`rate`, commodity_pulse→
# `commodity`) — the tool's own name primes the LLM to reach for that word as the param. NONE of these may
# collide with a REAL param of a tool that uses _dq (checked: `country`/`queries`/`type`/`entity_type` are
# real params → deliberately NOT aliased).
_Q_ALIASES = ("q", "query", "name", "commodity", "symbol", "keyword", "concept", "term",
              "theme", "sector", "industry", "bond", "rate", "topic", "asset")
_TICKER_ALIASES = ("ticker", "symbol", "q", "query", "stock", "asset", "name", "company")
def _dq(desc: str):  # noqa: ANN201 — free-text concept/search field
    return Field(description=desc, validation_alias=AliasChoices(*_Q_ALIASES))
def _dt(desc: str):  # noqa: ANN201 — exact-ticker field
    return Field(description=desc, validation_alias=AliasChoices(*_TICKER_ALIASES))
# multi-ticker field: schema exposes canonical `tickers`, but ALSO accept the singular `ticker`/`symbol(s)` an LLM
# reaches for on a single-company ask (measured: clients try `ticker=` first, hit an error, retry with `tickers`).
def _dts(desc: str):  # noqa: ANN201
    return Field(description=desc, validation_alias=AliasChoices("tickers", "ticker", "symbols", "symbol"))
_TICKER = "A MarketDX ticker OR a plain company/asset NAME — the SERVER resolves it for you (no separate lookup step). " \
    "🌐 LANGUAGE: a COMPANY / specific-asset NAME passes AS-IS in the user's own language (茅台/トヨタ/삼성 resolve " \
    "natively — do NOT translate a proper name, translation risks a wrong match); but a generic COMMODITY / SECTOR " \
    "CONCEPT must be ENGLISH (ทองคำ/黄金→'gold', 原油→'crude oil', 半導体→'semiconductors') — a raw non-English concept " \
    "word DRIFTS and misses. 🔴 Pass the user's FULL request in `context` (any language) so the server can tell which " \
    "'apple' you mean (the company vs the fruit-commodity), etc. If it's still genuinely ambiguous you get a " \
    "`needs_confirmation` reconfirm listing candidates — settle it from your CONVERSATION context if obvious (re-call " \
    "with the chosen exact ticker) or ASK the user, then re-call. An exact ticker passes straight through (mdx uses its " \
    "OWN suffixes: Korea `.KO`, Taiwan `.TW`, commodities `.COMM`, crypto `.CC`, FX `.FOREX`, bonds `.GB`, rates `.MM`)."
_TK_CONTEXT = "OPTIONAL but RECOMMENDED — paste the user's FULL request VERBATIM (any language: 'ขอราคาผลไม้ apple', " \
    "'compare Apple and Microsoft stock'). The server uses it to disambiguate which candidate each `ticker` entity " \
    "means (the apple COMPANY vs the fruit COMMODITY; which Samsung). One context per call, shared by all tickers here."
_WINDOW = "News-recency window: `7d`/`30d`/`90d`/`180d`/`1y` or `mtd`/`qtd`/`ytd`. Omit → a sensible default. " \
    "(Price history is unaffected — this only scopes the NEWS lens.)"
_LIMIT = "Max rows (default 20, hard cap 50). Keep SMALL + narrow the scope; page/refine rather than dump — " \
    "heavily-covered assets have hundreds of articles."
_FROM = "Lower time bound, ISO date `YYYY-MM-DD`. ⚠️ mdx NEWS coverage starts 2026-01-01 (nothing before)."
_TO = "Upper time bound, ISO date `YYYY-MM-DD`."
_DIRECTION = "Filter by impact direction: `pos` | `neg` | `ambiguous`. Omit → all."
_COLLAPSE = "Merge near-duplicate stories (same article from many outlets) into one row + `dup_count`. " \
    "Default ON; pass `false` for the raw un-deduped feed."
_COUNTRY_CSV = ("Market filter — CSV of ISO-2 codes (e.g. `US` or `CN,TW,HK`). 🌍 If the question names a NATIONALITY "
                "or REGION ('European','Thai','Chinese','ASEAN'), put it HERE — never leave it inside a concept/`q`/"
                "`gics` field. Enumerate a region into its member ISO-2s yourself (Europe→GB,DE,FR,IT,ES,NL,CH,SE; "
                "ASEAN→TH,SG,MY,ID,PH,VN).")
_ASPECT = "Impact CHANNEL filter (e.g. `demand`, `competition`, `tariff`, `monetary`). Omit → all channels."
_MEGATREND = "A megatrend node — a name/slug (resolved for you, e.g. `foundry`) or an int node id. CSV for several."
_GICS = ("A GICS sector/industry — a CODE PREFIX (sector `25` / group `2550` / industry `255010` / sub `25501010`, "
         "CSV for several) OR plain English ('banks', 'semiconductors', 'biotech'); the server resolves it. 🔴 ENGLISH "
         "(translate the concept first: ธนาคาร→'banks'). So 'European banks' = gics='banks' + country=EU codes.")
_NEWS_TYPE = "News CATEGORY (exact names only, e.g. `macro_economic`, `commodity_supply`, `earnings_results`)."
_PID = "The portfolio's id (call list_portfolios first if the user says 'my portfolio' without a number)."

def _lim(n: Optional[int], default: int = 20, ceiling: int = 50, floor: int = 1) -> int:
    """Bound a list tool's page size so the result stays context-friendly. Heavily-covered assets
    (GOLD, oil, mega-caps) have hundreds of impact articles — dumping them all overflows the client's
    context. `None` → default; the LLM may raise it up to `ceiling`, then should page/narrow instead.
    `floor` guards any TOP-K resolver endpoint: it returns a CANDIDATE LIST the client
    PICKS from, so a client setting limit=1 would collapse them to rank-#1 and break the design — floor it
    (e.g. 5) so a candidate list always comes back."""
    if n is None:
        return default
    return max(floor, min(int(n), ceiling))

# News exists only from here (backfill floor; still walking backward). There is NO news before this.
# Price/EOD history, by contrast, goes back decades — so historical volatility is answerable, news isn't.
_NEWS_COVERAGE_START = "2026-01-01"

def _win(window: Optional[str]) -> Optional[str]:
    """Resolve a relative/calendar `window` ('90d','1y','mtd','qtd','ytd') to a `from_` ISO date (to=now)
    — an LLM-friendlier alternative to computing dates by hand. Unknown/None → None (no lower bound).
    Explicit `from_`/`to` always take precedence over this."""
    if not window:
        return None
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    w = window.strip().lower()
    try:
        if w.endswith("d") and w[:-1].isdigit():
            return (now - _dt.timedelta(days=int(w[:-1]))).date().isoformat()
        if w.endswith("y") and w[:-1].isdigit():
            return (now - _dt.timedelta(days=365 * int(w[:-1]))).date().isoformat()
        if w == "mtd":
            return now.replace(day=1).date().isoformat()
        if w == "ytd":
            return now.replace(month=1, day=1).date().isoformat()
        if w == "qtd":
            return now.replace(month=3 * ((now.month - 1) // 3) + 1, day=1).date().isoformat()
    except Exception:
        return None
    return None

def _coverage_note(from_: Optional[str]) -> Optional[str]:
    """If a requested range starts before news coverage, a caller-facing warning so the LLM never reads
    an empty/short result as 'no news happened' (it's 'no coverage')."""
    if from_ and str(from_)[:10] < _NEWS_COVERAGE_START:
        return (f"Requested range starts before MarketDX news coverage (news begins {_NEWS_COVERAGE_START}; "
                "there is NO news before 2026). Results are limited to the covered window — do NOT present an "
                "empty/short result as 'nothing happened'. Price/volatility history DOES go back decades.")
    return None

def _ser(items: list) -> list:
    """SDK returns typed @dataclass models; MCP needs JSON — convert to plain dicts."""
    return [asdict(x) if is_dataclass(x) else x for x in items]

def _paged(page, key: str = "items") -> dict:
    """Wrap a paginated SDK result so the LLM can SEE truncation. Returns
    {<key>:[…], count, total, note?}. Without this the tool hands back a bare list and the LLM
    presents a curated subset as if it were the whole set (e.g. 23 of 50 theme members, silently)."""
    items = _ser(page.to_list())
    out: dict = {key: items, "count": len(items)}
    total = page.total          # cheap — populated from the first page's `total` field during to_list()
    if total is not None:
        out["total"] = total
        if total > len(items):
            out["note"] = (f"showing {len(items)} of {total} — this is a curated top slice, not the full "
                           f"list; tell the user more exist, and raise `limit` or narrow the scope to see them")
    return out

# ── per-request identity (hosted) + client cache ─────────────────────────────
# HTTP transport: each request carries its OWN caller's key (Authorization header → _req_key,
# set by the ASGI auth middleware in main()), so users are metered on THEIR account — never a
# shared server key. stdio/local: no header → fall back to MARKETDX_API_KEY env.
_req_key: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("marketdx_req_key", default=None)
_clients: dict[str, MarketDX] = {}   # key → client (reuse the httpx pool across a user's calls)

def mdx() -> MarketDX:
    key = _req_key.get() or os.environ.get("MARKETDX_API_KEY")
    if not key:
        raise RuntimeError("no MarketDX API key — send 'Authorization: Bearer <key>' (hosted) "
                           "or set MARKETDX_API_KEY (local). Get one at https://marketdx.lab.ai")
    cli = _clients.get(key)
    if cli is None:
        if len(_clients) > 512:   # coarse bound — MVP; swap for an LRU if it ever matters
            _clients.clear()
        base = os.environ.get("MARKETDX_BASE_URL")   # local/staging override; unset in prod → SDK default
        cli = _clients[key] = MarketDX(api_key=key, base_url=base) if base else MarketDX(api_key=key)
    return cli

def _check(resp):
    """Raise with the server's JSON error BODY, not a bare status. `_check(resp)` throws
    "Client error '400 Bad Request'" and DROPS the body — but the body is where the actionable message lives
    ("unknown param 'zzz' — declared params: […]", "pattern 'squeeze' needs operand a"). Surfacing it turns
    blind trial-and-error into a self-correcting client."""
    if resp.status_code >= 400:
        try:
            j = resp.json()
            msg = j.get("error") or j.get("detail") or resp.text
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        raise ValueError(str(msg))
    return resp

def _bget(path: str, params: Optional[dict] = None) -> dict:
    """Backend GET → `.data`, with bounded retry+backoff on TRANSIENT 429/5xx/timeout (same `_retry` policy as
    the Jev calls). Use for the RESOLVER retrieval leg (the vector `/find` + `/v1/stocks` endpoints) so a
    momentary backend blip doesn't fail a resolution. A non-transient error (404/400/402) raises as before."""
    return _retry(lambda: mdx()._get(path, params or {}).data, what="backend")

def _ext(path: str, params: dict) -> dict:
    """Call a `/v1/ext/*` (HS/Comtrade) endpoint and RELAY a user-actionable failure as a friendly dict
    (with the server's plain-language `note` + any BYOK CTA fields) instead of raising — so the client LLM
    surfaces a call-to-action / retries with a different param, never a stack trace. `byok_missing` (402),
    `byok_invalid` (402), rate-limit (429), bad-param (400) all come back this way; the `note` says whether
    to fall back to general knowledge meanwhile."""
    try:
        return _retry(lambda: mdx()._get(path, params).data, what="backend")
    except MarketDXError as e:
        out: dict = {"error": str(e), "note": getattr(e, "note", None)}
        resp = getattr(e, "response", None)
        if resp is not None:
            try:  # read the structured body DIRECTLY (robust to SDK versions that don't parse `note`):
                b = resp.json()  # BYOK gate → {error, provider, note, connect_url, signup_url}
                if isinstance(b, dict):
                    for k in ("error", "note", "provider", "connect_url", "signup_url"):
                        if b.get(k):
                            out[k] = b[k]
            except Exception:
                pass
        return out

def _deepseek(system: str, user: str, temperature: float) -> dict:
    """Our server-side LLM for the composite tools. deepseek reasoning OFF (fast/cheap)."""
    from openai import OpenAI
    cli = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/v1")
    r = cli.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature, response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(r.choices[0].message.content)

# ── Jev (TypeSafe System One) — server-side DECISION model for RESOLVER picks. ─────────────────────────
# Replaces the client's "read top-k and choose" pass: hand Jev the vector shortlist (from the existing
# /v1/*/find endpoints), it returns ONE choice + confidence, and a CALIBRATED gate decides
# resolve / soft-surface / reconfirm / no_match. Collapses a resolver round-trip. PoC + calibration:
# Ava repo jobs/jev-poc (resolver-replacement-design.md §4-6, calibrate_reconfirm.py).
_JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
_JEV_MODEL = "jev-latest"

import time as _time, random as _random, urllib.error as _uerr, concurrent.futures as _futures
_RETRY_STATUS = {429, 500, 502, 503, 504, 529}   # transient — retry with backoff
_RETRY_ATTEMPTS = 3

def _retry(fn, *, what="upstream"):
    """Bounded retry+backoff for TRANSIENT upstream failures (429/5xx/timeout/conn). Runs INSIDE the user's
    request → capped (3 attempts, ≤8s/step). Honors `Retry-After`. NEVER retries a deterministic 4xx
    (400/401/402/404 → raise immediately, e.g. bad-param / byok_missing / not-found)."""
    for i in range(_RETRY_ATTEMPTS):
        try:
            return fn()
        except (_uerr.URLError, MarketDXError) as e:
            if isinstance(e, _uerr.HTTPError):
                transient = e.code in _RETRY_STATUS
                ra = e.headers.get("Retry-After") if e.headers else None
            elif isinstance(e, _uerr.URLError):        # non-HTTP URLError = timeout / conn reset / DNS
                transient, ra = True, None
            else:                                       # backend SDK typed error (RateLimitError/APIError)
                transient = getattr(e, "status", None) in _RETRY_STATUS
                ra = getattr(e, "retry_after", None)
            if not transient or i == _RETRY_ATTEMPTS - 1:
                raise
            try:
                delay = float(ra) if ra else 0.0
            except (TypeError, ValueError):
                delay = 0.0
            if delay <= 0:
                delay = 0.4 * (2 ** i) + _random.uniform(0, 0.4)   # 0.4-0.8 / 0.8-1.2 / …
            _time.sleep(min(delay, 8.0))

def _jev_post(payload: dict, timeout: int) -> dict:
    """POST to TypeSafe (System One) with bounded retry+backoff. Shared by _jev_pick / _jev_picks / _jev_nouls."""
    import urllib.request
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("no TYPESAFE_API_KEY set (Jev resolver)")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(_JEV_ENDPOINT, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    def _do():
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    return _retry(_do, what="jev")

def _pick_stats(a: dict) -> dict:
    """Shape ONE Jev choice answer → {pick, confidence, p1, p2, gap, probs}."""
    probs = a.get("probabilities") or {}
    top = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    p1 = top[0][1] if top else (a.get("confidence") or 0.0)
    p2 = top[1][1] if len(top) > 1 else 0.0
    return {"pick": a.get("choice"), "confidence": a.get("confidence"),
            "p1": p1, "p2": p2, "gap": round(p1 - p2, 3), "probs": dict(top[:4])}

def _jev_picks(questions: dict, state_query: str = "") -> dict:
    """BATCH Choice — MANY picks in ONE TypeSafe call (docs: 'ask every Choice question in a single request';
    questions run in parallel, 'adding questions barely changes response time'). `questions` =
    {key: {"instructions": str, "options": {opt: desc}}}. Returns {key: _pick_stats(...)} — same per-key shape
    as _jev_pick. Each key carries its OWN entity in its instructions (state.query is shared context)."""
    if not questions:
        return {}
    qs = {k: {"type": "choice", "instructions": v["instructions"], "criteria": v["options"]}
          for k, v in questions.items()}
    answers = _jev_post({"model": _JEV_MODEL, "state": {"query": state_query}, "questions": qs}, 30).get("answers", {})
    return {k: _pick_stats(answers.get(k) or {}) for k in questions}

def _jev_pick(query: str, instructions: str, options: dict) -> dict:
    """ONE Jev Choice over `options` ({choice_key: description}). Returns
    {pick, confidence, p1, p2, gap, probs} — p1/p2 = top-two probabilities, gap = their margin."""
    a = _jev_post({"model": _JEV_MODEL, "state": {"query": query},
                   "questions": {"pick": {"type": "choice", "instructions": instructions, "criteria": options}}},
                  20).get("answers", {}).get("pick", {})
    return _pick_stats(a)

def _jev_gate(r: dict) -> str:
    """Calibrated reconfirm gate (jev-poc/calibrate_reconfirm.py, pooled 117 — re-validate in full-loop).
    resolve = silent · soft = resolve+note (non-blocking) · reconfirm = ask (two close) · no_match = flat."""
    conf = r.get("confidence") or 0.0
    gap = r.get("gap", 1.0)
    p1 = r.get("p1") or 0.0
    p2 = r.get("p2") or 0.0
    if conf >= 0.85:
        return "resolve"
    if p1 < 0.40 and gap < 0.15:
        return "no_match"
    if p2 >= 0.30 and gap < 0.30:
        return "reconfirm"
    return "soft"

def _jev_nouls(query: str, questions: dict) -> dict:
    """N independent yes/no COVERAGE decisions in ONE TypeSafe call (fan-out, cheap). `questions` = {id: instruction}.
    Returns {id: prob 0..1}. Noul = a calibrated boolean; MULTI-LABEL (keep each ≥ threshold) — unlike Choice which
    softmaxes onto one. Mirrors megatrend-mapper jev.rs `nouls`."""
    qs = {qid: {"type": "noul", "instructions": instr} for qid, instr in questions.items()}
    answers = _jev_post({"model": _JEV_MODEL, "state": {"query": query}, "questions": qs}, 30).get("answers", {})
    out = {}
    for qid in questions:
        a = answers.get(qid) or {}
        v = a.get("noul", a.get("probability", a.get("confidence")))
        out[qid] = float(v) if v is not None else 0.0
    return out

def _jev_noul(query: str, instruction: str) -> float:
    """ONE coverage Noul → prob 0..1."""
    return _jev_nouls(query, {"q": instruction}).get("q", 0.0)

# ── UNIFIED concept resolver (collapse find_gics + find_megatrend). English industry/theme concept → typed refs
#    [{type:"theme"|"gics", id, name}] (multi-label). Vector (search_concepts: BOTH taxonomies, one shared query
#    embed) → coverage Noul per candidate (ONE _jev_nouls call) → theme-priority-with-guard. No gazetteer/deepseek.
_CONCEPT_NOUL_KEEP = 0.5   # coverage threshold (calibrate from probes)
_CONCEPT_DIRECT_BAR = 0.65  # top coverage below this = an INDIRECT (last-resort / closest-home) match → flag it
_CONCEPT_THEME_WIN = 0.75   # theme beats gics only if its top coverage ≥ this AND ≥ the top gics

_concept_cache: dict = {}   # normalized-English concept → resolved envelope (in-process; the query EMBED is already
                            # persistently cached backend-side in query_embedding_cache, so this only spares the Jev
                            # Noul round-trip on a repeated term within a server lifetime — and pins a stable answer
                            # despite Jev's run-to-run ±0.05 jitter). Cleared on restart; a persistent table is a
                            # future add if cross-restart repeat proves worth a migration.

def _resolve_concept(concept: str) -> dict:
    """One English INDUSTRY/THEME concept → typed refs (result-cached by normalized concept). Returns
    {status:'resolved', query, axis:'theme'|'gics', refs:[{type,id,name,prob}]} | {status:'no_match', …}."""
    ck = " ".join(str(concept).strip().lower().split())
    if ck and ck in _concept_cache:
        return dict(_concept_cache[ck])
    res = _resolve_concept_uncached(concept)
    if ck and res.get("status") in ("resolved", "no_match"):
        _concept_cache[ck] = res
    return dict(res)

def _resolve_concept_uncached(concept: str) -> dict:
    q = str(concept).strip()
    data = _bget("/v1/search/concepts", {"q": q, "limit": 12})
    themes = (data.get("themes") or []) if isinstance(data, dict) else []
    sectors = (data.get("sectors") or []) if isinstance(data, dict) else []
    if not themes and not sectors:
        return {"status": "no_match", "query": q, "reason": "no theme/sector candidate (vector)", "candidates": []}
    def _ctx(name, text):  # context parity: the candidate's name + the exact text that was embedded (its description)
        t = (text or "").strip()
        return f"«{name}»" + (f" — {t}" if t and t.lower() != str(name).strip().lower() else "")
    # Framing = TIGHT (rejects a too-broad parent + a related sibling → strong precision), paired with a LOW keep
    # threshold so a correct-but-slightly-wider home that only scores modestly (luxury→"Apparel/Accessories/Luxury"
    # ~0.34; cloud sub-themes ~0.33) still survives (recall). The ancestor-rollup then cleans granularity.
    qmap, meta = {}, {}
    for i, t in enumerate(themes):
        qid, nm = f"t{i}", t.get("name", "")
        qmap[qid] = (f"An investor wants to screen the '{q}' group. Candidate megatrend/theme: {_ctx(nm, t.get('text'))}. "
                     f"Is «{nm}» a place where '{q}' companies squarely live — is it '{q}', or a node whose members are "
                     f"MOSTLY '{q}'? Answer NO if «{nm}» is MUCH broader than '{q}' (a parent mostly holding non-'{q}' "
                     f"names) or merely RELATED/adjacent (not itself '{q}').")
        meta[qid] = {"type": "theme", "id": t.get("node_id"), "name": nm, "axis": "theme", "score": t.get("score")}
    for i, s in enumerate(sectors):
        qid, nm, lv = f"g{i}", s.get("name", ""), s.get("level", "")
        qmap[qid] = (f"An investor wants to screen the '{q}' group. Candidate GICS {lv}: {_ctx(nm, s.get('text'))}. "
                     f"Is «{nm}» a place where '{q}' companies squarely live — is it '{q}', or a classification whose "
                     f"constituents are MOSTLY '{q}'? Answer NO if «{nm}» is MUCH broader (a parent sector mostly "
                     f"holding non-'{q}' industries) or a merely-related SIBLING that is not itself '{q}'.")
        meta[qid] = {"type": "gics", "id": s.get("code"), "name": nm, "axis": "gics", "score": s.get("score")}
    probs = _jev_nouls(q, qmap)
    kept = [(qid, probs.get(qid, 0.0)) for qid in qmap if probs.get(qid, 0.0) >= _CONCEPT_NOUL_KEEP]
    themes_k = sorted([(meta[k].copy(), p) for k, p in kept if meta[k]["axis"] == "theme"], key=lambda x: -x[1])
    gics_k = sorted([(meta[k].copy(), p) for k, p in kept if meta[k]["axis"] == "gics"], key=lambda x: -x[1])
    # theme-priority WITH BREADTH GUARD. A curated theme is the higher-value grouping (client can't know it), so it
    # WINS when it's a strong fit (≥_CONCEPT_THEME_WIN). BUT when a strong GICS also exists, only let the theme win if
    # it covers ROUGHLY THE WHOLE concept — not a narrow slice: 'semiconductors'→"Semiconductors" theme = whole → win;
    # 'healthcare'→"Home Healthcare & Hospice" = a slice → fall to the GICS Health Care sector. (One extra Noul, only
    # in the both-strong case.)
    theme_top = themes_k[0][1] if themes_k else 0.0
    gics_top = gics_k[0][1] if gics_k else 0.0
    prefer_theme = bool(themes_k) and (not gics_k or theme_top >= _CONCEPT_THEME_WIN)
    if prefer_theme and gics_k and gics_top >= 0.75:
        tn = themes_k[0][0]["name"]
        breadth = _jev_noul(q, f"An investor asks for the '{q}' group. Does the theme «{tn}» cover ROUGHLY THE WHOLE "
                               f"'{q}' universe — most of what an investor means by '{q}'? Answer near 1 if it spans "
                               f"most of '{q}'; near 0 if «{tn}» is only a NARROW SLICE/subset of '{q}'.")
        if breadth < 0.5:
            prefer_theme = False
    chosen = themes_k if prefer_theme else (gics_k or themes_k)
    if not chosen:
        return {"status": "no_match", "query": q, "reason": "no covering theme/sector (all Nouls below threshold)", "candidates": []}
    if chosen[0][0]["axis"] == "gics":
        # ROLLUP: the Noul keeps a group + its industry + sub-industries (all individually cover X). (1) cluster kept
        # codes by their 4-digit GROUP, LCP within each → the group-covering code; (2) ancestor-dedup: drop a code
        # another kept code is a prefix of (a kept SECTOR absorbs its groups). 'banks' → [4010]; 'healthcare' → [35];
        # 'retail' → [2550, 3010] (multi-home). Clustering by GROUP (not sector) stops a stray 'Asset-Mgmt & Custody
        # Banks' (grp 4020) from dragging Banks (grp 4010) up to the Financials sector.
        by_grp: dict = {}
        for m, p in chosen:
            by_grp.setdefault(str(m["id"])[:4], []).append((str(m["id"]), m["name"], p))
        cov = []
        for grp, items in by_grp.items():
            codes = [c for c, _, _ in items]
            s1, s2 = min(codes), max(codes)
            i = 0
            while i < len(s1) and i < len(s2) and s1[i] == s2[i]:
                i += 1
            anc = s1[: i - (i % 2)] or grp
            cov.append((anc, next((n for c, n, _ in items if c == anc), items[0][1]), max(p for _, _, p in items)))
        final = []
        for code, name, pp in sorted(cov, key=lambda x: len(x[0])):   # shortest (broadest) first
            if not any(code != o[0] and code.startswith(o[0]) for o in final):
                final.append((code, name, pp))
        refs = [{"type": "gics", "id": c, "name": n, "prob": round(p, 3)} for c, n, p in sorted(final, key=lambda x: -x[2])]
        return {"status": "resolved", "query": q, "axis": "gics", "refs": refs,
                "indirect": bool(refs) and max(r["prob"] for r in refs) < _CONCEPT_DIRECT_BAR}
    # THEME axis rollup, mirror of gics but on the megatrend id scheme (TTSSLLDD, ancestor = zero the rightmost
    # pairs). Cluster kept themes by TIER-1 (TT000000); drop a stray tier-1 cluster far below the top; within each
    # kept cluster take the BROADEST kept node (most trailing zeros = highest tier). Downstream expands the subtree,
    # so the tier-1 covers its children. 'semiconductors' → [56000000]; 'cloud computing' → [28000000] (+ any other
    # genuinely-strong tier-1). A single narrow leaf (robotaxi) stays itself — it's the only kept node in its cluster.
    by_t1: dict = {}
    for m, p in chosen:
        by_t1.setdefault((int(m["id"]) // 1000000) * 1000000, []).append((m["id"], m["name"], p))
    cov = []
    for _t1, items in by_t1.items():
        best = max(items, key=lambda it: (len(str(it[0])) - len(str(it[0]).rstrip("0")), it[2]))
        cov.append(best)
    refs = [{"type": "theme", "id": c, "name": n, "prob": round(p, 3)} for c, n, p in sorted(cov, key=lambda x: -x[2])]
    return {"status": "resolved", "query": q, "axis": "theme", "refs": refs,
            "indirect": bool(refs) and max(r["prob"] for r in refs) < _CONCEPT_DIRECT_BAR}

def _scope_resolve(val):
    """Resolve a universe-SCOPE argument (a sector/theme CONCEPT, a raw code/id, or a CSV/list of them) via the
    unified `_resolve_concept`, and SPLIT the result by type so the caller can route it. Returns
    (gics_codes:list[str], theme_ids:list[int], confirm|None, resolved_map). A pure-digit token is passed straight
    through as a GICS code (the raw-id path); an English concept is resolved and may yield gics AND/OR theme refs
    (e.g. 'AI' → a theme id, 'biotech' → a gics code). Any unresolved token → ONE batched reconfirm envelope."""
    if not val:
        return [], [], None, {}
    toks = [str(t).strip() for t in (val if isinstance(val, list) else str(val).split(",")) if str(t).strip()]
    gcodes, tids, pend, rmap = [], [], {}, {}
    for t in toks:
        if t.isdigit():                       # raw GICS code already in hand → passthrough
            gcodes.append(t); continue
        r = _resolve_concept(t)
        if r["status"] != "resolved":
            pend[t] = {"kind": "scope", "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])}
            continue
        for ref in r["refs"]:
            (gcodes if ref["type"] == "gics" else tids).append(ref["id"] if ref["type"] == "gics" else int(ref["id"]))
        rmap[t] = {"axis": r["axis"], "ids": [ref["id"] for ref in r["refs"]], "indirect": r.get("indirect", False)}
    if pend:
        return [], [], {"needs_confirmation": True, "resolved": rmap, "confirm": pend,
                        "_guide": "A universe-scope term isn't a recognized sector/theme — pick one from its candidates "
                                  "(or drop it), then RE-CALL with the chosen code/id (a bare GICS code / theme id passes "
                                  "straight through)."}, rmap
    return gcodes, tids, None, rmap

def _theme_node(concept):
    """A THEME-only tool's subject → ONE megatrend node id (the top theme ref), via the unified resolver.
    Returns (node_id:int, None) on success; (None, error_dict) when the concept is NOT a curated theme — either a
    pure GICS sector (honest 'that's a sector, use a screen') or no_match. A bare numeric id passes through."""
    if concept is None:
        return None, None
    s = str(concept).strip()
    if s.isdigit():
        return int(s), None
    r = _resolve_concept(s)
    themes = [x for x in r.get("refs", []) if x["type"] == "theme"]
    if themes:
        return int(themes[0]["id"]), None
    if r.get("status") != "resolved":
        return None, {"needs_confirmation": True, "query": s,
                      "confirm": {s: {"status": r.get("status"), "reason": r.get("reason"), "candidates": r.get("candidates", [])}},
                      "_guide": "That isn't a recognizable megatrend/theme — pick from candidates, or use a sector screen."}
    return None, {"not_a_theme": True, "query": s, "resolved_axis": "gics", "gics": [x["id"] for x in r["refs"]],
                  "_guide": f"'{s}' is a GICS sector/industry ({r['refs'][0]['name']}), not a curated megatrend theme — "
                            f"use a sector screen (screen_unified/screen_stocks with gics='{s}')."}

def _theme_nodes(spec):
    """CSV/list of theme TERMS and/or ids → csv of megatrend node ids (multi; numeric passes through), via the
    unified resolver. Returns (csv_or_None, error_dict_or_None) — error only when NOTHING resolves to a theme."""
    if not spec:
        return None, None
    toks = [t.strip() for t in (spec if isinstance(spec, list) else str(spec).split(",")) if str(t).strip()]
    ids, pend = [], {}
    for t in toks:
        nid, err = _theme_node(t)
        if nid is not None:
            if nid not in ids:
                ids.append(nid)
        elif err:
            pend[t] = err
    if ids:
        return ",".join(str(i) for i in ids), None
    if pend:
        return None, {"needs_confirmation": True, "confirm": pend,
                      "_guide": "None of these are recognizable megatrend themes — pick from candidates or use a sector screen."}
    return None, None

_FS_RESOLVE_INSTR = (
    "The state has `query`: a natural-language financial concept (any language, often loose/colloquial/slangy) a "
    "user wants to read or screen on. Each option is one catalog concept — its type (field=a statement line · "
    "ratio=a derived ratio · valuation=a price multiple), label, and definition. Select the SINGLE option that "
    "best matches the query's MEANING. Human phrasing is rarely exact, so a LOOSE or APPROXIMATE match to a real "
    "concept is CORRECT — always prefer the nearest real concept. For a near-duplicate cluster (basic vs diluted, "
    "gross vs net, reported vs normalized, current vs non-current, asset vs liability) pick the standard headline "
    "UNLESS the user named the variant. One option is `__NONE__` (no concept matches) — read its description; it "
    "is a LAST RESORT for queries in a DIFFERENT DOMAIN entirely, NEVER for imperfectly-worded real concepts. "
    "Match on meaning, not surface wording.")

# no_match as an explicit Choice option — lets Jev say "nothing fits" instead of being FORCED to pick a
# nearest-but-wrong candidate (vector KNN always returns k). Worded to bias HARD toward matching: the dangerous
# error is a loose real concept wrongly sent to NONE (false-negative). Validated 0/17 false-neg, 6/6 recall.
_NONE_OPT = (
    "None of the concepts above. ⚠️ Choose this ONLY as a LAST RESORT — when the query is about something in a "
    "COMPLETELY DIFFERENT DOMAIN than company financial statements / ratios / valuation multiples (e.g. a market-"
    "sentiment or ESG score, an analyst price target, a technical or price indicator, a macro-economic series, a "
    "non-financial attribute). Human wording is loose, colloquial, slangy, vague, or approximate — that is NORMAL "
    "and MUST still match the closest real concept. Do NOT choose NONE for an imperfect, informal, or roughly-"
    "worded phrasing of a real financial concept; whenever the query is even loosely in the financial-statement "
    "domain, prefer the nearest real concept. Pick NONE only when nothing here is remotely what the user means.")

def _resolve_fsconcept(q: str, scope_types: tuple = ("field", "ratio", "valuation"), statement: Optional[str] = None) -> dict:
    """Resolve ONE natural-language OR exact-key term → the catalog concept, SCOPED to `scope_types`
    (the set of catalogs the calling tool's input legitimately accepts: financials.fields={field};
    screen_unified.concept={field,ratio,valuation}). Flow: exact-key passthrough → else vector shortlist
    (/v1/financials/find?verbose=1, FULL context parity: label+definition+description+aliases) → Jev pick + `__NONE__`
    → calibrated gate. Returns {status: resolved|reconfirm|no_match, query, key?, type?, confidence?, gate?, note?, candidates?}."""
    data = _bget("/v1/financials/find", {"q": q, "statement": statement, "limit": 15, "verbose": 1})
    all_cands = data.get("candidates", []) if isinstance(data, dict) else []
    cands = [c for c in all_cands if c.get("type", "field") in scope_types]  # SCOPE: only catalogs this input accepts
    if not cands:
        return {"status": "no_match", "query": q, "reason": "no in-scope candidates", "candidates": []}
    # FAST-PATH: the client sent an EXACT catalog key already (in scope) → use it, skip Jev (no resolve needed).
    qn = q.strip().lower()
    exact = next((c for c in cands if str(c.get("concept", "")).lower() == qn), None)
    if exact:
        return {"status": "resolved", "query": q, "key": exact["concept"], "type": exact.get("type"),
                "confidence": 1.0, "gate": "exact_key"}
    options, meta = {}, {}
    for c in cands:
        concept, typ = c.get("concept"), c.get("type", "field")
        if not concept:
            continue
        k = f"{typ}:{concept}"
        # full context parity: label + definition + description + aliases (+ statement tag)
        desc = f"[{typ}] {c.get('label', '')}."
        if c.get("definition"):
            desc += " " + c["definition"]
        if c.get("description"):
            desc += " " + c["description"]
        if c.get("aliases"):
            desc += " Also called: " + ", ".join(c["aliases"]) + "."
        if c.get("statement"):
            desc += f" (statement={c['statement']})"
        options[k] = desc
        meta[k] = {"concept": concept, "type": typ, "label": c.get("label")}
    options["__NONE__"] = _NONE_OPT  # explicit no_match option (bias-to-match; see _NONE_OPT)
    r = _jev_pick(q, _FS_RESOLVE_INSTR, options)
    if r.get("pick") == "__NONE__":  # Jev says nothing in the shortlist fits → no_match (out-of-domain query)
        return {"status": "no_match", "query": q, "reason": "not a financial-statement concept (Jev: none of the candidates fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"concept": meta[k]["concept"], "type": meta[k]["type"], "label": meta[k]["label"], "prob": round(v, 3)}
                 for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "key": pm.get("concept"), "type": pm.get("type"),
               "confidence": r.get("confidence"), "gate": gate}
        if gate == "soft":
            alts = ", ".join(c["concept"] for c in top_cands[1:3])
            out["note"] = f"resolved '{q}' → {pm.get('concept')} at lower confidence; alternatives considered: {alts}"
        return out
    reason = "two close candidates — confirm which" if gate == "reconfirm" else "no confident match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

# ── TICKER resolution — the find_stock refactor: same vector→Jev→gate pattern as _resolve_fsconcept, but the
#    IDENTITY axis. Turns a bare symbol / company name → the exact MarketDX ticker. It does NOT touch the
#    canonical head — that is the consuming endpoint's job (financials→head, stock_prices→the literal listing);
#    a shared resolver must stay identity-only or it would break price/pulse (GOOGL.US≠GOOG.US price). See
#    resolver-replacement-design.md §13.
# SCOPE-AWARE instruction/NONE — the acceptable asset classes depend on the CONSUMING tool's scope. A stock-only
# scope (financials/relationships) must REJECT a commodity/crypto/bond as no_match; a broad price/pulse scope must
# RESOLVE them (they're valid tradables). So the wording is built from `scope`, not hardcoded to companies. (The
# parity A/B run14 caught the company-centric version wrongly no_match'ing gold/bitcoin/US-10Y/SOFR/SPY.)
_TYPE_LABEL = {
    "stock":     "a listed company / stock (this class ALSO covers a government-bond YIELD `<ISO2>-<TENOR>.GB` and a money-market RATE `<TOKEN>.MM`)",
    "etf":       "an ETF / fund",
    "commodity": "a commodity (metal / energy / agri, e.g. GOLD.COMM)",
    "crypto":    "a cryptocurrency",
    "forex":     "a currency / FX pair",
    "private":   "a private / off-coverage company (oc:…)",
}
def _ticker_instr(scope: tuple) -> str:
    accepted = "; ".join(_TYPE_LABEL.get(t, t) for t in scope)
    return (
        "The state has `query`: what identifies ONE instrument to resolve. It may be a bare name/symbol, OR the form "
        "'Resolve the entity \"X\" as it is used in the user's request: \"<full request>\"' — in that case resolve the "
        "ENTITY X, using the full request as the disambiguating CONTEXT (e.g. entity 'apple' in request 'ราคาผลไม้ apple' "
        "/ 'price of the fruit apple' → the apple COMMODITY; in 'apple stock price' → the company). Each option is a "
        "candidate listing: name, ticker, asset type, country/exchange, and a market-cap size hint. The ONLY asset "
        f"classes acceptable for THIS request are: {accepted}. The query (+ its context) is your primary evidence:\n"
        "1. If the query WORDING points to ONE candidate, pick it confidently: a fuller/proper NAME that matches one "
        "('Apple Inc', 'Samsung Electronics'); a KIND word — stock/shares/equity, commodity/futures/spot, ETF/fund, "
        "crypto/coin, currency/FX, bond/yield/rate — → the candidate of that class; a metric only ONE kind has "
        "(earnings/revenue/PE/dividend/market-cap → a COMPANY, never a commodity); a country/exchange; or an exact "
        "ticker SYMBOL (a bare symbol → the listing whose symbol equals it: GOOGL → the GOOGL class, not GOOG, unless "
        "only one is present).\n"
        "2. If the query is a BARE word/symbol with NO such signal, judge whether it has ONE overwhelmingly dominant "
        "everyday meaning among the candidates. YES — a raw-material word ('gold'/'copper') ≈ the spot commodity; ONE "
        "famous entity ('Toyota'/'Nvidia') with only tiny same-named others → pick that dominant one. NO — the bare "
        "word genuinely SPLITS across distinct real things (SEVERAL real companies of comparable stature; OR a major "
        "company AND a same-named commodity that are BOTH ordinary readings, e.g. 'apple' = the tech giant AND an apple "
        "fruit commodity) → you are genuinely UNCERTAIN: DO NOT guess one. SPREAD your probability across the tied "
        "candidates (keep your top confidence MODERATE) so the ambiguity is handed back to the user to settle from "
        "their own context — do not concentrate on a single guess.\n"
        "3. `__NONE__`: only when NO candidate is an accepted-class instrument that the query names.\n"
        "Use the market-cap / name / type hints ONLY as evidence of what each candidate is and which meaning is "
        "dominant — do NOT mechanically 'always pick the biggest'. Match on identity + the query's intent, not spelling.")
def _ticker_none(scope: tuple) -> str:
    return (
        "None of the listings is an instrument (of the accepted classes for this request) that the query names. "
        "⚠️ LAST RESORT — pick this ONLY when the query is not a resolvable instrument at all (pure gibberish / not a "
        "real name or symbol), or every candidate belongs to an asset class this request does NOT accept. A name, "
        "symbol, commodity, crypto, FX, bond/rate, or ETF that DOES match a candidate of an ACCEPTED class must "
        "resolve to that candidate, never to NONE.")

def _ticker_prep(q: str, scope: tuple = ("stock",), country: Optional[str] = None,
                 context: Optional[str] = None) -> dict:
    """PREP (retrieval + fast-path + Jev options) for a ticker resolution — NO Jev call. Returns a TERMINAL dict
    (status set: fast-path `resolved` / `no_match`) when no decision is needed, else a `_pending` dict
    {jev_q, scope, options, meta} to feed ONE _jev_pick (single) or a batched _jev_picks (plural).
    Resolve ONE entity (company name / bare symbol / alias / non-English name) → the exact MarketDX ticker,
    SCOPED to asset `scope`. RETRIEVAL uses `q` (the ENTITY — a company name passes native; a commodity/sector
    concept must be English, per the field contract). `context` = the user's FULL request; it is what JEV judges
    with, so it can tell which candidate the entity means ('apple' the company vs the fruit-commodity). Flow: full
    ticker (AAPL.US) → passthrough; else vector shortlist on `q` → Jev pick (judged by `context`, falling back to
    `q`) + `__NONE__` → calibrated gate. IDENTITY only — head/listing mapping is the endpoint's job. Returns
    {status: resolved|reconfirm|no_match, query, ticker?, name?, confidence?, gate?, note?, candidates?}."""
    matches = _bget("/v1/stocks", {"q": q, "country": country, "limit": 15}).get("matches", [])
    cands = [m for m in matches if m.get("type") in scope]   # SCOPE: only asset classes this tool accepts
    if not cands:
        return {"status": "no_match", "query": q, "reason": f"no {'/'.join(scope)} listing matches", "candidates": []}
    # `matched_via` = a cross-listing whose symbol matched the query but was collapsed to its canonical head
    # (GOOGL → row GOOG.US via GOOGL.US · NVDA → row NVDA.US via a FOREIGN line NVDA.SW). It is METADATA about what
    # TRIGGERED the match, NOT the user's intent (NVDA.SW is Swiss, not what "NVDA" means) — so RETURN the row's
    # `ticker` (the canonical/primary listing /v1/stocks chose; correct for financials via resolve_head, consistent
    # with find_stock). Use matched_via ONLY to DETECT that the query hit this row (fast-path) + as Jev context.
    def _syms(m):  # every symbol this row could have matched the query on (its own + the cross-listing it collapsed)
        return {t.split(".")[0].upper() for t in (m.get("ticker"), m.get("matched_via"), m.get("symbol")) if t}
    qn = q.strip().upper()
    # FAST-PATH: a UNIQUE row whose symbol == the query → unambiguous ticker entry, no Jev (NVDA/RDDT/MSFT/GOOGL).
    # 🔴 GUARD: only when the user typed a DELIBERATE TICKER SYMBOL — an ALL-UPPERCASE single token (`NVDA`, `AAPL`,
    # `KBANK`). A lowercase common WORD ('apple', 'gold', 'samsung') that merely happens to equal a commodity's symbol
    # ('APPLE'/'GOLD') must NOT fast-path — it defers to Jev, which reads the word's meaning (apple → the company /
    # genuinely ambiguous, not the Fuji-apple commodity). Several rows (same symbol across countries) → Jev too.
    ticker_shaped = q.strip().isupper() and " " not in q.strip() and "." not in q.strip()
    exact = [m for m in cands if m.get("match_type") in ("symbol", "cross_listing", "exact") and qn in _syms(m)]
    if ticker_shaped and len(exact) == 1:
        return {"status": "resolved", "query": q, "ticker": exact[0].get("ticker"), "name": exact[0].get("name"),
                "confidence": 1.0, "gate": "exact_symbol"}
    def _mc(m):  # market-cap size hint → lets Jev prefer a mega-cap COMPANY over a same-named MINOR commodity/fund
        v = m.get("market_cap_usd")
        if not v: return None
        if v >= 1e12: return f"~${v/1e12:.1f}T mkt cap (mega-cap)"
        if v >= 1e9:  return f"~${v/1e9:.0f}B mkt cap"
        if v >= 1e6:  return f"~${v/1e6:.0f}M mkt cap"
        return None
    options, meta = {}, {}
    for m in cands:
        idt = m.get("ticker")                                # IDENTITY = the canonical/primary listing to return
        if not idt:
            continue
        parts = [p for p in (m.get("type"), m.get("country") or m.get("region"),
                             (f"exch {m['exchange']}" if m.get("exchange") else None), _mc(m)) if p]
        desc = f"{m.get('name', '')} ({idt})" + (" — " + ", ".join(parts) if parts else "")
        if m.get("match_type") == "cross_listing" and m.get("matched_via"):
            desc += f" [matched the query via {m['matched_via']} — same company]"
        options[idt] = desc
        meta[idt] = {"ticker": idt, "name": m.get("name")}
    options["__NONE__"] = _ticker_none(scope)
    # JEV judges with the user's FULL request (context) so it can disambiguate which candidate the entity means;
    # the ENTITY (`q`) is stated explicitly so Jev knows WHICH thing to resolve within a compound request. No
    # context → fall back to the bare entity (still resolves the dominant reading).
    jev_q = (f'Resolve the entity "{q}" as it is used in the user\'s request: "{context.strip()}"'
             if context and context.strip() and context.strip().lower() != q.strip().lower() else q)
    return {"_pending": True, "query": q, "jev_q": jev_q, "scope": scope, "options": options, "meta": meta}

def _ticker_finish(prep: dict, r: dict) -> dict:
    """Gate + shape a Jev pick `r` for a prepared ticker resolution — shared by the single and BATCH paths."""
    q, meta = prep["query"], prep["meta"]
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": "not a listed company matching the query (Jev: none fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"ticker": meta[k]["ticker"], "name": meta[k]["name"], "prob": round(v, 3)}
                 for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "ticker": pm.get("ticker"), "name": pm.get("name"),
               "confidence": r.get("confidence"), "gate": gate}
        if gate == "soft":
            alts = ", ".join(c["ticker"] for c in top_cands[1:3])
            out["note"] = f"resolved '{q}' → {pm.get('ticker')} at lower confidence; alternatives: {alts}"
        return out
    reason = "same name/symbol across markets or entities — confirm which" if gate == "reconfirm" else "no confident company match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

def _ticker_batch_instr(prep: dict) -> str:
    """Instructions for a BATCH pick entry — scope instr + the entity/context (state.query is shared in a batch,
    so the per-entity signal moves into each question's instructions; parity-verified vs the single form)."""
    return _ticker_instr(prep["scope"]) + "\n\nRESOLVE THE ENTITY DESCRIBED HERE: " + prep["jev_q"]

def _resolve_ticker(q: str, scope: tuple = ("stock",), country: Optional[str] = None,
                    context: Optional[str] = None) -> dict:
    """Resolve ONE entity → the exact MarketDX ticker (SINGLE path — behavior unchanged): prep → one Jev pick →
    gate. Returns {status: resolved|reconfirm|no_match, query, ticker?, name?, confidence?, gate?, note?, candidates?}."""
    prep = _ticker_prep(q, scope, country, context)
    if not prep.get("_pending"):
        return prep
    r = _jev_pick(prep["jev_q"], _ticker_instr(scope), prep["options"])
    return _ticker_finish(prep, r)

# ── TICKER-ARG collapse (find_stock → its consumers). Per-consumer SCOPE = the asset classes that tool legitimately
#    accepts. Verified from live /v1/stocks `type` values: stock (INCLUDES bond-yield .GB + money-market rate .MM),
#    etf, commodity, crypto, forex, private. `_ticker_arg`/`_tickers_arg` mirror the financials walk (server.py ~2430):
#    an exact full ticker passes through (no Jev); a name/symbol/phrase → _resolve_ticker → resolved | batched reconfirm.
_SCOPE_STOCK      = ("stock",)                                              # financials, relationships (companies)
_SCOPE_OPTIONABLE = ("stock", "etf")                                       # options_sentiment (US-optionable)
_SCOPE_ASSET      = ("stock", "etf", "crypto")                             # asset_pulse (company/ETF/crypto; commodity→commodity_pulse per its own doc)
_SCOPE_PRICED     = ("stock", "etf", "commodity", "crypto", "forex")       # stock_prices(_batch) (priced instruments; private has no prices)
_SCOPE_BROAD      = ("stock", "etf", "commodity", "crypto", "forex", "private")  # stock_impact (news impact on any asset)

def _is_full_ticker(tok: str) -> bool:
    """A real full ticker `SYMBOL.EXCH` — the suffix is an exchange code (≥2 LETTERS: US/TW/LSE/KO/COMM/CC/GB/MM/
    FOREX…) → dual-mode PASSTHROUGH (identity already in hand). A dotted symbol whose suffix is NOT alpha (BRK.B —
    ".B" is a share class) is NOT a full ticker → falls to resolve (mirrors financials server.py:2422-2426)."""
    suffix = tok.rsplit(".", 1)[1] if "." in tok else ""
    return len(suffix) >= 2 and suffix.isalpha()

_TICKER_CONFIRM_GUIDE = ("This name/ticker isn't uniquely resolved — pick the exact `ticker` from candidates (or add "
                         "`country` to disambiguate a same-name company across markets), then RE-CALL with it (a full "
                         "ticker `SYMBOL.EXCH` passes straight through, no re-resolve).")
_TK_COUNTRY = ("OPTIONAL market disambiguator — pass ONLY when `ticker` is a plain NAME that collides across markets "
               "(the Thai vs Korean 'KBANK'); omit for a distinctive name or an exact ticker (an unneeded country "
               "silently 0-matches). A country NAME or ISO-2 code ('South Korea'/'KR'); the server normalizes, so pass "
               "the NAME when unsure — never GUESS a 2-letter code ('CH' = Switzerland, not China).")

def _ticker_arg(val, scope=_SCOPE_STOCK, country=None, context=None):
    """Resolve ONE ticker arg: exact full ticker → passthrough; else name/symbol/phrase → `_resolve_ticker` (SCOPED,
    disambiguated by `context` = the user's full request). Returns (ticker|None, confirm|None, detail). `confirm` !=
    None on reconfirm/no_match — the caller returns it verbatim (kind='ticker'). `detail` = observability."""
    tok = str(val or "").strip()
    if not tok:
        return None, None, {}
    if _is_full_ticker(tok):
        return tok, None, {}
    r = _resolve_ticker(tok, scope=scope, country=country, context=context)
    if r["status"] == "resolved":
        det = {"ticker": r.get("ticker"), "confidence": r.get("confidence"), "gate": r.get("gate")}
        if r.get("note"): det["note"] = r["note"]
        return r["ticker"], None, {tok: det}
    return None, {"needs_confirmation": True, "resolved": {},
                  "confirm": {tok: {"kind": "ticker", "status": r["status"], "reason": r.get("reason"),
                                    "candidates": r.get("candidates", [])}},
                  "_guide": _TICKER_CONFIRM_GUIDE}, {}

def _tickers_arg(vals, scope=_SCOPE_PRICED, country=None, context=None):
    """Plural — resolve a list/CSV of ticker args → (tickers:list, confirm|None, detail). Full tickers pass through;
    the rest resolve (each disambiguated by the shared `context` = the user's full request); ANY pending token → ONE
    batched reconfirm (return WITHOUT querying). Mirrors financials' tk_pending walk so a watchlist resolves in one shot."""
    toks = [str(t).strip() for t in (vals if isinstance(vals, list) else str(vals).split(",")) if str(t).strip()]
    detail, pend, resolved = {}, {}, {}   # resolved: tok -> ticker (preserves input order at assembly)
    def _record(tok, r):
        if r["status"] == "resolved":
            det = {"ticker": r.get("ticker"), "confidence": r.get("confidence"), "gate": r.get("gate")}
            if r.get("note"): det["note"] = r["note"]
            resolved[tok] = r["ticker"]; detail[tok] = det
        else:
            pend[tok] = {"kind": "ticker", "status": r["status"], "reason": r.get("reason"),
                         "candidates": r.get("candidates", [])}
    prepped = {}                          # tok -> prep needing a Jev decision
    concept_toks = []
    for tok in toks:
        if _is_full_ticker(tok):
            resolved[tok] = tok                              # dual-mode passthrough — no Jev / no retrieval
        else:
            concept_toks.append(tok)
    if concept_toks:                      # 🆕 PARALLEL retrieval — independent /v1/stocks GETs, never a serial loop
        mdx()                             # warm the cached httpx client before fan-out (dodge a first-create race)
        with _futures.ThreadPoolExecutor(max_workers=min(8, len(concept_toks))) as ex:
            preps = list(ex.map(lambda t: _ticker_prep(t, scope, country, context), concept_toks))
        for tok, prep in zip(concept_toks, preps):
            if prep.get("_pending"):
                prepped[tok] = prep
            else:
                _record(tok, prep)                           # fast-path resolved / no_match — no Jev
    if prepped:                           # 🆕 BATCH — ALL pending tokens in ONE Jev call (was one call per token)
        qmap = {tok: {"instructions": _ticker_batch_instr(p), "options": p["options"]} for tok, p in prepped.items()}
        picks = _jev_picks(qmap, state_query="")
        for tok, p in prepped.items():
            _record(tok, _ticker_finish(p, picks.get(tok) or {}))
    if pend:
        return [], {"needs_confirmation": True, "resolved": detail, "confirm": pend, "_guide": _TICKER_CONFIRM_GUIDE}, detail
    return [resolved[t] for t in toks if t in resolved], None, detail

# ── FSPATTERN resolution — the find_fspattern refactor: SHAPE axis (the temporal pattern to screen on), same
#    vector→Jev→gate pattern as _resolve_fsconcept. Resolver picks the SHAPE only; its `params` (threshold/N/…)
#    are filled DOWNSTREAM by the client from the user's stated numbers, never invented here. See design §15.
_FSPATTERN_RESOLVE_INSTR = (
    "The state has `query`: a natural-language description of a TEMPORAL PATTERN / SHAPE a user wants to screen "
    "companies on ('grew every year', 'margin expanding', 'below the sector average', 'cheapest 10%', 'debt rising "
    "faster than equity', 'doubled in 2 years'). Each option is one screener pattern — its kind (level=an absolute "
    "threshold · cohort=peer-relative · quadrant · relation=two metrics compared · parametric=a windowed shape), "
    "label, and definition. Select the SINGLE option whose SHAPE best matches the query's MEANING and DIRECTION. "
    "Ignore the specific metric and any numbers (those are supplied separately) — match only the SHAPE. Prefer the "
    "plain headline shape unless the query names a sharper variant ('grew every year' → consecutive_growth, not "
    "the SHARP variant unless the user said 'sharply/strongly'). One option is `__NONE__` — read its description; "
    "it is a LAST RESORT for a query that is NOT a screenable temporal shape at all.")

_FSPATTERN_NONE_OPT = (
    "None of the patterns above. ⚠️ LAST RESORT ONLY — pick this when the query does not describe a screenable "
    "temporal SHAPE at all (it's a bare metric with no shape, a company/identifier, or something off-domain). Loose, "
    "informal, or approximate wording of a real shape ('going up steadily', 'keeps beating peers') is NORMAL and "
    "MUST still match the nearest real pattern; choose NONE only when nothing here is remotely the shape meant.")

def _resolve_fspattern(q: str) -> dict:
    """Resolve ONE natural-language TEMPORAL PATTERN → the screener `pattern` shape (for screen_unified conditions).
    Flow mirrors _resolve_fsconcept: exact-key passthrough → vector shortlist (/v1/financials/find-pattern, full
    context: label+definition+params+basis_hint) → Jev pick + `__NONE__` → calibrated gate. Returns
    {status, query, pattern?, kind?, params?, confidence?, gate?, note?, candidates?}. The pattern's `params`
    (threshold/N/min/max/percentile/total_change) ride along for the CLIENT to fill from the user's numbers —
    the resolver never invents them."""
    data = _bget("/v1/financials/find-pattern", {"q": q, "limit": 15})
    cands = data.get("patterns", data.get("candidates", [])) if isinstance(data, dict) else []
    if not cands:
        return {"status": "no_match", "query": q, "reason": "no candidate patterns", "candidates": []}
    # FAST-PATH: the client already sent an exact pattern token → use it, skip Jev.
    qn = q.strip().lower()
    exact = next((c for c in cands if str(c.get("pattern", "")).lower() == qn), None)
    if exact:
        return {"status": "resolved", "query": q, "pattern": exact["pattern"], "kind": exact.get("kind"),
                "params": exact.get("params"), "confidence": 1.0, "gate": "exact_key"}
    options, meta = {}, {}
    for c in cands:
        pat = c.get("pattern")
        if not pat:
            continue
        # full context parity: kind + label + definition (+ basis hint)
        desc = f"[{c.get('kind', 'pattern')}] {c.get('label', '')}."
        if c.get("definition"):
            desc += " " + c["definition"]
        if c.get("basis_hint"):
            desc += f" (basis: {c['basis_hint']})"
        options[pat] = desc
        meta[pat] = {"pattern": pat, "kind": c.get("kind"), "label": c.get("label"), "params": c.get("params")}
    options["__NONE__"] = _FSPATTERN_NONE_OPT
    r = _jev_pick(q, _FSPATTERN_RESOLVE_INSTR, options)
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": "not a screenable temporal shape (Jev: none of the patterns fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"pattern": meta[k]["pattern"], "kind": meta[k]["kind"], "label": meta[k]["label"], "prob": round(v, 3)}
                 for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "pattern": pm.get("pattern"), "kind": pm.get("kind"),
               "params": pm.get("params"), "confidence": r.get("confidence"), "gate": gate}
        if gate == "soft":
            alts = ", ".join(c["pattern"] for c in top_cands[1:3])
            out["note"] = f"resolved '{q}' → {pm.get('pattern')} at lower confidence; alternatives considered: {alts}"
        return out
    reason = "two close pattern shapes — confirm which" if gate == "reconfirm" else "no confident pattern match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

# ── TASIGNAL resolution — the find_tasignal refactor (ta leg of screen_unified). find_tasignal is 2-AXIS: each
#    phrase → `signals` (SHAPE patterns) + `indicators` (operand LINES), two embeddings from /v1/ta/find-signal.
#    Per design §16 we resolve EACH TaSignal field INDEPENDENTLY (client splits {pattern,a,b}; the server resolves
#    them in parallel, no server-side a/b derivation): `pattern` → signals axis, `a`/`b` → indicators axis. Same
#    dual-mode as every other resolver (exact key/token → passthrough, else Jev pick over the top_k). 🔴 the whole
#    top_k is fed to Jev — never judge the axis by rank-1 (golden cross's ema/sma sit BELOW macd in the shortlist).
def _is_numeric_level(v: str) -> bool:
    """PURE SYNTAX (not vocab): True if an a/b value is a numeric LEVEL / fraction / lo-hi range ('80', '0',
    '0.30', '40-50') — a level, not a chart line → pass it through, never resolve. (Whether an operand is a valid
    indicator TOKEN is decided by the resolver's exact-check against the ENDPOINT candidates, not a hardcoded set.)"""
    s = str(v).strip()
    return bool(s) and all(c.isdigit() or c in ".-" for c in s)

def _period_from(q: str) -> str:
    """First run of digits in an operand phrase → the PERIOD to append to a periodized line ('the 50-day'→'50',
    'the 200-day moving average'→'200'). '' if the phrase names no number. Mirrors the old client's 'append the
    period the user asked' assembly step."""
    m = re.search(r"\d+", str(q))
    return m.group(0) if m else ""

def _find_signal(q: str) -> dict:
    """One phrase → both axes ({signals, indicators}) from /v1/ta/find-signal (batch-of-1)."""
    data = mdx()._http._client.post("/v1/ta/find-signal", json={"queries": [q], "limit": 15})
    _check(data)
    res = (data.json().get("results") or [{}])
    return res[0] if res else {}

_TASIGNAL_RESOLVE_INSTR = (
    "The state has `query`: a natural-language TECHNICAL-ANALYSIS shape a user wants to screen on ('golden cross', "
    "'rsi crossing above 80', 'breaking out of a squeeze', 'price rolling over', 'volume surge'). Each option is one "
    "chart PATTERN — its direction (up/down/neutral) + description. Select the SINGLE option whose SHAPE and "
    "DIRECTION best match the query. Ignore the specific indicator lines (those resolve separately) — match only the "
    "SHAPE. Prefer the plain headline pattern unless the query names a sharper/variant form. One option is "
    "`__NONE__` — a LAST RESORT for a query that is NOT a screenable chart shape at all.")

_TASIGNAL_NONE_OPT = (
    "None of the patterns above. ⚠️ LAST RESORT ONLY — the query does not describe a screenable chart SHAPE (it's a "
    "bare indicator name with no shape, a fundamental metric, a company, or off-domain). Loose/informal wording of a "
    "real chart shape is NORMAL and MUST still match the nearest pattern; choose NONE only when nothing here fits.")

_TAINDICATOR_RESOLVE_INSTR = (
    "The state has `query`: a natural-language reference to a chart LINE / indicator used as an operand ('the "
    "50-day average', 'the cloud', 'trend strength', 'volatility', 'the signal line', 'the fast stochastic'). Each "
    "option is one indicator line — its family + definition. Select the SINGLE line the query refers to (the "
    "30-day average→ema/sma, 'trend strength'→adx, 'volatility'→atr, 'the cloud'→senkou_a/senkou_b, 'the signal "
    "line'→macd_signal). Match on MEANING. One option is `__NONE__` — a LAST RESORT when the query names no chart "
    "line at all.")

_TAINDICATOR_NONE_OPT = (
    "None of the indicator lines above. ⚠️ LAST RESORT ONLY — the query does not name a chart line/indicator "
    "operand (it's a shape, a number, a company, or off-domain). A loose reference to a real line ('the 30-day', "
    "'momentum', 'the bands') is NORMAL and MUST still match the nearest line; choose NONE only when nothing fits.")

def _resolve_ta_axis(q: str, axis: str, key_field: str, instr: str, none_opt: str, extra: tuple = ()) -> dict:
    """Shared resolver for ONE TaSignal field over ONE axis of find-signal. `axis` = 'signals' | 'indicators';
    `key_field` = 'pattern' | 'indicator'. exact-key passthrough → Jev pick + `__NONE__` → calibrated gate.
    `extra` = extra keys to carry from the chosen candidate into the result (e.g. 'direction'/'family')."""
    cands = _find_signal(q).get(axis, [])
    if not cands:
        return {"status": "no_match", "query": q, "reason": f"no candidate {key_field}s", "candidates": []}
    # exact-key passthrough — compare against the ENDPOINT candidates (catalog), like the other resolvers; a
    # period-suffixed operand (ema50/rsi14) matches the base candidate (ema/rsi) → keep the ORIGINAL (backend snaps).
    qn = q.strip().lower()
    qn_base = qn.rstrip("0123456789")
    exact = next((c for c in cands if str(c.get(key_field, "")).lower() == qn), None)
    ret = exact.get(key_field) if exact else None
    if not exact and qn_base and qn_base != qn:
        exact = next((c for c in cands if str(c.get(key_field, "")).lower() == qn_base), None)
        ret = q.strip() if exact else None
    if exact:
        out = {"status": "resolved", "query": q, key_field: ret, "confidence": 1.0, "gate": "exact_key"}
        for k in extra:
            if exact.get(k) is not None: out[k] = exact[k]
        return out
    options, meta = {}, {}
    for c in cands:
        key = c.get(key_field)
        if not key:
            continue
        # context parity (§15): feed the UNION the pipeline uses, not just one field — signals carry
        # archetype+direction+description, indicators family+definition+description.
        tag = c.get("direction") or c.get("family") or ""
        desc = ". ".join(b for b in (c.get("archetype"), c.get("description"), c.get("definition")) if b)
        options[key] = (f"[{tag}] " if tag else "") + f"{key}. {desc}"
        meta[key] = {key_field: key, **{k: c.get(k) for k in extra}}
    options["__NONE__"] = none_opt
    r = _jev_pick(q, instr, options)
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": f"not a screenable {key_field} (Jev: none fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{key_field: meta[k][key_field], "prob": round(v, 3)} for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, key_field: pm.get(key_field), "confidence": r.get("confidence"), "gate": gate}
        for k in extra:
            if pm.get(k) is not None: out[k] = pm[k]
        if gate == "soft":
            out["note"] = f"resolved '{q}' → {pm.get(key_field)} at lower confidence"
        return out
    reason = f"two close {key_field}s — confirm which" if gate == "reconfirm" else f"no confident {key_field} match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

def _resolve_tasignal(q: str) -> dict:
    """NL chart shape → screener `pattern` (signals axis). Carries `direction`."""
    return _resolve_ta_axis(q, "signals", "pattern", _TASIGNAL_RESOLVE_INSTR, _TASIGNAL_NONE_OPT, extra=("direction",))

def _resolve_ta_indicator(q: str) -> dict:
    """NL chart line → operand `indicator` (indicators axis). Carries `family`.
    Final assembly step (old CLIENT's, moved server-side): after Jev resolves the LINE, append the PERIOD the user
    named in the phrase ('the 50-day' → ema50; the backend snaps it). Only when the phrase carries a number and the
    resolved base isn't already periodized — lines with no number (adx/rsi/close/macd_signal…) stay bare. Exact-key
    passthrough (client already sent 'ema50') is untouched."""
    r = _resolve_ta_axis(q, "indicators", "indicator", _TAINDICATOR_RESOLVE_INSTR, _TAINDICATOR_NONE_OPT, extra=("family",))
    if r.get("status") == "resolved" and r.get("gate") != "exact_key":
        base = str(r.get("indicator") or "")
        per = _period_from(q)
        if per and base and not base[-1].isdigit():
            r["indicator"] = base + per
    return r

# ── OPPATTERN resolution — the find_oppattern refactor (options-behaviour leg of screen_unified + options_scan).
#    Same vector→Jev→gate pattern as _resolve_fspattern. Carries exec_path so the caller routes scan vs compose vs
#    unsupported (compose_recipe = catalog DATA the caller expands by reusing the ta resolver). See design §15.
_OPPATTERN_RESOLVE_INSTR = (
    "The state has `query`: a natural-language phrase describing an OPTIONS-MARKET BEHAVIOUR / crowd emotion a user "
    "wants to find stocks by ('who is the crowd afraid of', 'cheap implied vol', 'smart money piling in', 'one-sided "
    "/ crowded names', 'options positioning fighting the price'). Pro jargon (IV rank, skew, gamma, put/call) AND "
    "newbie emotion words (fear, greed, confidence, betting) both map here. Each option is one options pattern — its "
    "dimension (fear_greed / implied_vol / positioning / …), temporal_mode (level=the state NOW · rising/falling=a "
    "~2-week TREND · flip=a REVERSAL), label, and description. 🔴 KEEP THE TENSE the user used — a state NOW ('who is "
    "the crowd afraid of') vs a trend ('fear is building') vs a flip ('were afraid, now getting brave') are DIFFERENT "
    "options; match the temporal_mode to the query's tense. Select the SINGLE option whose behaviour + tense best "
    "match the query's MEANING. One option is `__NONE__` — a LAST RESORT for a query that is NOT an options-market "
    "behaviour at all.")

_OPPATTERN_NONE_OPT = (
    "None of the options patterns above. ⚠️ LAST RESORT ONLY — pick this when the query is NOT about options-market "
    "behaviour (it's a plain price/fundamental screen, one named stock's option detail, a company, or off-domain). "
    "Loose or emotional wording of a real options behaviour ('the crowd is nervous', 'everyone's betting one way') is "
    "NORMAL and MUST still match the nearest pattern; choose NONE only when nothing here is remotely about options.")

def _resolve_oppattern(q: str) -> dict:
    """Resolve ONE natural-language OPTIONS-BEHAVIOUR phrase → the opana `pattern` token (for options_scan /
    screen_unified.options). Mirrors _resolve_fspattern: exact-key passthrough → vector shortlist
    (/v1/options/find-pattern, full context: dimension+temporal_mode+label+description) → Jev pick + `__NONE__` →
    calibrated gate. Carries `temporal_mode`, `exec_path`, `supported`, and `compose_recipe` (when present) so the
    caller can route scan vs compose vs unsupported."""
    resp = mdx()._http._client.post("/v1/options/find-pattern", json={"q": q, "limit": 15})
    _check(resp)
    data = resp.json()
    cands = data.get("patterns", []) if isinstance(data, dict) else []
    if not cands:
        return {"status": "no_match", "query": q, "reason": "no candidate options patterns", "candidates": []}
    def _carry(c):  # the fields the caller needs to ROUTE (scan/compose/unsupported)
        out = {"pattern": c.get("pattern"), "temporal_mode": c.get("temporal_mode"),
               "exec_path": c.get("exec_path"), "supported": c.get("supported")}
        if c.get("compose_recipe") is not None: out["compose_recipe"] = c.get("compose_recipe")
        return out
    # FAST-PATH: the client already sent an exact pattern token → use it, skip Jev (compare to ENDPOINT candidates).
    qn = q.strip().lower()
    exact = next((c for c in cands if str(c.get("pattern", "")).lower() == qn), None)
    if exact:
        return {"status": "resolved", "query": q, "confidence": 1.0, "gate": "exact_key", **_carry(exact)}
    options, meta = {}, {}
    for c in cands:
        pat = c.get("pattern")
        if not pat:
            continue
        # context parity: feed the union — dimension + temporal_mode (tense) + label + description.
        tag = c.get("dimension") or ""
        desc = (f"[{tag}] " if tag else "") + f"{c.get('label', '')}."
        if c.get("temporal_mode"): desc += f" (tense: {c['temporal_mode']})"
        if c.get("description"): desc += " " + c["description"]
        options[pat] = desc
        meta[pat] = c
    options["__NONE__"] = _OPPATTERN_NONE_OPT
    r = _jev_pick(q, _OPPATTERN_RESOLVE_INSTR, options)
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": "not an options-market behaviour (Jev: none fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"pattern": k, "label": meta[k].get("label"), "prob": round(v, 3)} for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "confidence": r.get("confidence"), "gate": gate, **_carry(pm)}
        if gate == "soft":
            out["note"] = f"resolved '{q}' → {pm.get('pattern')} at lower confidence"
        return out
    reason = "two close options patterns — confirm which" if gate == "reconfirm" else "no confident options pattern match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

_TAX: Optional[dict] = None
def _taxonomy() -> dict:
    global _TAX
    if _TAX is None:
        nodes = _ser(mdx().megatrends().to_list())
        children: dict = {}
        for n in nodes:
            children.setdefault(n.get("parent_id"), []).append(n)
        _TAX = {"nodes": nodes, "by_id": {n["id"]: n for n in nodes},
                "by_name": {n["name"]: n for n in nodes}, "children": children}
    return _TAX

def _node_out(nid: int) -> dict:
    n = _taxonomy()["by_id"][nid]
    return {"id": nid, "name": n["name"], "tier": n["tier"]}


# ── SIMPLE tools (thin SDK wrappers — client LLM orchestrates) ────────────────
# The valid news_type names (GET /v1/news/types) — used to sanitize a hallucinated value before it
# hard-errors the API. Keep in sync with the API's list.
_NEWS_TYPES = {"product_tech", "ma_partnership", "industry_thematic", "earnings_results",
               "corporate_action", "management_governance", "analyst_rating", "macro_economic",
               "geopolitics", "commodity_supply", "regulatory_legal", "cybersecurity_digital_trust",
               "digital_finance_tokenization", "price_action_technical", "noise_other", "short_news",
               "crypto_related", "forex_related", "analyst_forecast"}

# The 64 opana-covered ETFs → concept label (from ava_listings.asset_type='ETF'). Doubles as the asset-
# angle resolver vocabulary for theme_pulse and the authoritative "which ETF is covered" set.
_COVERED_ETFS = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "DIA": "Dow 30", "MDY": "S&P Midcap 400",
    "XLK": "Technology sector", "XLF": "Financials sector", "XLE": "Energy sector", "XLV": "Healthcare sector",
    "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLI": "Industrials", "XLU": "Utilities",
    "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services",
    "SMH": "Semiconductors", "SOXX": "Semiconductors", "XBI": "Biotech", "IBB": "Biotech",
    "KRE": "Regional Banks", "OIH": "Oil Services", "XOP": "Oil & Gas E&P", "XRT": "Retail",
    "JETS": "Airlines", "TAN": "Solar", "ARKK": "ARK disruptive-innovation / high-growth tech",
    "GLD": "Gold", "SLV": "Silver", "USO": "Crude Oil",
    "UNG": "Natural Gas", "GDX": "Gold Miners", "GDXJ": "Junior Gold Miners", "TLT": "20y+ Treasuries",
    "IEF": "7-10y Treasuries", "AGG": "US Aggregate Bonds", "LQD": "Investment-Grade Corp",
    "HYG": "High-Yield Corp", "TIP": "TIPS", "EMB": "EM Bonds", "EEM": "Emerging Markets",
    "EFA": "Developed ex-US",
    "FXI": "China Large-Cap", "MCHI": "China (broad, MSCI China incl. ADRs/HK)",
    "ASHR": "China A-Shares (mainland CSI 300)", "KWEB": "China Internet / China tech",
    "EWH": "Hong Kong", "EWT": "Taiwan", "THD": "Thailand",
    "EWJ": "Japan", "EWY": "South Korea", "EWZ": "Brazil", "INDA": "India",
    "VXX": "VIX Volatility", "UVXY": "VIX 2x",
    "IBIT": "Bitcoin", "ETHA": "Ethereum", "SPXL": "S&P 3x Bull", "SPXU": "S&P 3x Bear",
    "TQQQ": "Nasdaq 3x Bull", "SQQQ": "Nasdaq 3x Bear", "SOXL": "Semis 3x Bull", "TZA": "Small-Cap 3x Bear",
    "YINN": "China 3x Bull (LEVERAGED)",
}

@mcp.tool(title="Theme Summary", annotations=_RO)
def theme_summary(theme: Annotated[str, _d("A megatrend theme — name/slug (resolved for you) or node id.")],
                  window: Annotated[str, _d(_WINDOW)] = "30d",
                  country: Annotated[Optional[str], _d("Optional market ISO-2 filter.")] = None) -> dict:
    """Pre-composed analyst brief for a megatrend theme: pulse, winners/losers, top entities, aspect
    heatmap, ripple. `theme` = a theme name or id/slug; `window` = 7d/30d/90d/1y/mtd/qtd/ytd."""
    node, err = _theme_node(theme)
    if err: return err
    return mdx().theme(node).summary(window=window, country=country)

@mcp.tool(title="Brief", annotations=_RO)
def brief(news_type: Annotated[Optional[str], _d(_NEWS_TYPE)] = None,
          country: Annotated[Optional[str], _d(_COUNTRY_CSV)] = None,
          aspect: Annotated[Optional[str], _d(_ASPECT)] = None,
          gics: Annotated[Optional[str], _d(_GICS)] = None,
          megatrend: Annotated[Optional[str], _d(_MEGATREND)] = None,
          window: Annotated[str, _d(_WINDOW)] = "30d",
          from_: Annotated[Optional[str], _d(_FROM)] = None,
          to: Annotated[Optional[str], _d(_TO)] = None,
          interval: Annotated[Optional[Literal["day","week","month"]], _d("Time-bucketing of the pulse series: `day`|`week`|`month`.")] = None,
          lang: Annotated[Optional[Literal["en","th","ja"]], _d("Translate title/brief_text: `en`|`th`|`ja`.")] = None) -> dict:
    """The generalized ANALYST BRIEF — one composed "how is <scope> doing right now?" picture (pulse +
    net direction, top_stories, winners/losers, aspect_heatmap, top_entities, top_assets) for ANY
    AND-combination of scopes. ⭐ Use this to SUMMARIZE a SCOPE — a THEME, a news CATEGORY, a COUNTRY, a
    SECTOR, or an aspect (NOT a raw article list → that's search_news/news_feed). ⛔ NOT for a single
    COMPANY or a market INDEX/ticker: "how is the S&P / Nasdaq / AAPL doing?" → `options_sentiment`
    (+ `stock_impact`/`news_feed`), because an index maps to an ETF asset (S&P→SPY), not a brief scope.
    For a SECTOR × REGION ("how are European banks doing?") the quickest path is `theme_pulse(q='banks',
    country=…)` (fans out, resolves the code for you). Use THIS (brief) when you want the ONE precise GICS
    cohort with no fan-out, or an AND-combo: pass the sector as a code OR plain English —
    `brief(gics='banks', country="GB,DE,FR,IT,ES,NL,CH,SE")` (enumerate the region's ISO-2s; server resolves the sector).
    Scope by ≥1 of (each takes a CSV for multiple values):
      • `news_type` — a news CATEGORY. Use ONLY these EXACT names (never invent one): product_tech,
        ma_partnership, industry_thematic, earnings_results, corporate_action, management_governance,
        analyst_rating, macro_economic, geopolitics, commodity_supply, regulatory_legal,
        cybersecurity_digital_trust, digital_finance_tokenization, price_action_technical, crypto_related,
        forex_related, analyst_forecast. ("สรุปข่าว commodity" → commodity_supply; central-bank/rates →
        macro_economic — there is NO 'monetary_policy').
      • `country` — an ISO-2 market. country='JP' → "how is Japan doing right now?".
      • `aspect` — an impact CHANNEL. aspect='tariff' → "everything moving via tariffs".
      • `gics` — a GICS sector/industry: a CODE prefix (sector 25 / group 2550 / industry 255010) OR plain English
        ('banks'), often × country. 'European banks' = gics='banks' + country=EU codes (server resolves the sector).
      • `megatrend` — a theme node id/slug. For a NAMED theme use `theme_summary` (it resolves free text);
        use `megatrend` here only when you already have the id or want to AND it with another scope.
    Combine (AND): news_type='commodity_supply'+country='JP' = commodity news in Japan; gics='2550'+
    country='GB,DE,FR,IT,ES,NL' = a European retail pulse. `window` = 7d/30d/90d/180d/1y/mtd/qtd/ytd (or
    pass from_/to as ISO dates). ≥1 scope is REQUIRED (it never scans everything). ⚠️ News coverage starts
    2026-01-01. `node`+`ripple` appear only when a SINGLE megatrend anchors the brief."""
    # Runtime-sanitize news_type: the client can hallucinate a name (e.g. 'monetary_policy') → the API
    # hard-errors. Drop unknowns so the valid scope still returns; flag what we dropped.
    dropped = []
    if news_type:
        req = [t.strip() for t in str(news_type).split(",") if t.strip()]
        news_type = ",".join(t for t in req if t in _NEWS_TYPES) or None
        dropped = [t for t in req if t not in _NEWS_TYPES]
    # UNIFIED concept resolution: `gics` and `megatrend` may be plain English or a code/id — the server resolves
    # and routes (a theme concept in `gics` flows into the megatrend leg; a sector concept in `megatrend` would too).
    _mts = []
    if megatrend:
        megatrend, _me = _theme_nodes(megatrend)
        if _me: return _me
    if gics:
        _g, _t, _cf, _ = _scope_resolve(gics)
        if _cf: return _cf
        gics = ",".join(_g) if _g else None
        _mts = [str(x) for x in _t]
    if _mts:
        megatrend = ",".join(_mts + ([megatrend] if megatrend else []))
    res = mdx().brief(megatrend=megatrend, news_type=news_type, country=country, aspect=aspect,
                      gics=gics, window=window, from_=from_, to=to, interval=interval, lang=lang)
    if dropped and isinstance(res, dict):
        res["_warning"] = (f"Ignored invalid news_type(s) {dropped} — not real categories. Valid names: "
                           f"{sorted(_NEWS_TYPES)}. (There is no 'monetary_policy'; use 'macro_economic'.)")
    return res

_SIM_STRONG = 0.68   # cosine ≥ this = a solid semantic match. ⚠️ CALIBRATE against real off-topic queries.
_SIM_WEAK = 0.58     # below this = essentially no match

@mcp.tool(title="Search News", annotations=_RO)
def search_news(q: Annotated[str, _dq("Free-text SEMANTIC news query — a topic/event/asset in any language "
                                      "('copper', 'oil shock', 'Fed rate hike', 'ข่าวทองคำ').")],
                entity_type: Annotated[Optional[Literal["stock","forex","crypto","commodity","private"]], _d("Keep only hits of one kind: `stock`|`forex`|`crypto`|`commodity`|`private`. Omit → all.")] = None,
                collapse: Annotated[Optional[bool], _d(_COLLAPSE)] = None,
                limit: Annotated[Optional[int], _d(_LIMIT)] = None,
                from_: Annotated[Optional[str], _d(_FROM)] = None,
                to: Annotated[Optional[str], _d(_TO)] = None,
                window: Annotated[Optional[str], _d(_WINDOW)] = None) -> dict:
    """SEMANTIC news search across ALL covered asset classes — stocks, FX, crypto, COMMODITIES (metals
    like copper/gold, energy like oil), and private companies. Articles matched by MEANING, impact-labeled
    (title, publisher, entities, direction, why). USE THIS for 'copper news', 'metals', 'gold', etc.
    instead of a web search. `entity_type` keeps only stock/forex/crypto/commodity/private hits. For a
    FILTERED feed by aspect/direction/country use `news_feed`. `limit` = how many (default 20, max 50).
    TIME-SCOPE with `from_`/`to` (ISO dates, e.g. '2026-04-01') or a `window` ('90d','qtd','ytd','1y').
    ⚠️ News coverage starts 2026-01-01 — older ranges return nothing (that's no COVERAGE, not 'no news').
    Returns {match_quality, top_similarity, note, results}. If match_quality is 'weak'/'none', the corpus
    has no strongly relevant news — do NOT present these results as evidence; say so and use another route."""
    frm = from_ or _win(window)
    results = _ser(mdx().news_search(q, entity_type=entity_type, collapse=collapse,
                                     from_=frm, to=to, limit=_lim(limit)).to_list())
    sims = [r.get("similarity") for r in results if isinstance(r.get("similarity"), (int, float))]
    top = max(sims) if sims else 0.0
    quality = "strong" if top >= _SIM_STRONG else ("weak" if top >= _SIM_WEAK else "none")
    note = _coverage_note(frm) or (None if quality == "strong" else (
        "Weak/no semantic match — MarketDX likely has no strongly relevant news for this query. Do NOT "
        "present these as evidence; tell the user, and use world knowledge / another tool instead."))
    return {"match_quality": quality, "top_similarity": round(top, 3), "note": note, "results": results}

@mcp.tool(title="News Feed", annotations=_RO)
def news_feed(megatrend: Annotated[Optional[str], _d(_MEGATREND)] = None,
              country: Annotated[Optional[str], _d(_COUNTRY_CSV)] = None,
              aspect: Annotated[Optional[str], _d(_ASPECT)] = None,
              direction: Annotated[Optional[Literal["pos","neg","ambiguous"]], _d(_DIRECTION)] = None,
              news_type: Annotated[Optional[str], _d(_NEWS_TYPE)] = None,
              only_scored: Annotated[Optional[bool], _d("Keep only articles carrying a judged per-entity impact. Omit → all gated articles.")] = None,
              min_relevance: Annotated[Optional[float], _d("Minimum impact relevance, 0–1.")] = None,
              limit: Annotated[Optional[int], _d(_LIMIT)] = None,
              collapse: Annotated[Optional[bool], _d(_COLLAPSE)] = None,
              from_: Annotated[Optional[str], _d(_FROM)] = None,
              to: Annotated[Optional[str], _d(_TO)] = None,
              window: Annotated[Optional[str], _d(_WINDOW)] = None) -> list:
    """The filtered impact feed — news by megatrend/country/aspect/direction/news_type, across stocks,
    FX, crypto, COMMODITIES (metals/energy) and private cos. Use for 'negative tariff news on
    Semiconductors', 'macro news moving European stocks', 'copper / metals news', etc. Near-duplicate
    stories are MERGED by default (+`dup_count`); `collapse=false` for the raw feed. `limit` = how many
    (default 20, max 50); narrow the filters rather than paging deep. TIME-SCOPE with `from_`/`to` (ISO)
    or a `window` ('90d','qtd','ytd','1y'). To COMPARE periods, call once per period and compare the
    results. ⚠️ News starts 2026-01-01 — older ranges return nothing (no coverage, not 'no news')."""
    # 🆕 collapse find_megatrend: `megatrend` may be a name/slug/plain-English concept — resolve to node id(s)
    # via the unified resolver (mirror of brief/screen_stocks); backend /v1/news accepts INT ids only.
    if megatrend:
        megatrend, _me = _theme_nodes(megatrend)
        if _me: return _me
    return _ser(mdx().news(megatrend=megatrend, country=country, aspect=aspect, direction=direction,
                          news_type=news_type, only_scored=only_scored, min_relevance=min_relevance,
                          collapse=collapse, from_=from_ or _win(window), to=to, limit=_lim(limit)).to_list())

@mcp.tool(title="Stock Impact", annotations=_RO)
def stock_impact(ticker: Annotated[str, _dt(_TICKER)],
                 direction: Annotated[Optional[Literal["pos","neg","ambiguous"]], _d(_DIRECTION)] = None,
                 limit: Annotated[Optional[int], _d(_LIMIT)] = None,
                 collapse: Annotated[Optional[bool], _d(_COLLAPSE)] = None,
                 from_: Annotated[Optional[str], _d(_FROM)] = None,
                 to: Annotated[Optional[str], _d(_TO)] = None,
                 country: Annotated[Optional[str], _d(_TK_COUNTRY)] = None,
                 window: Annotated[Optional[str], _d(_WINDOW)] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> list:
    """How news moved a specific company/asset (incl commodities like GOLD.COMM) — per-article impact
    (direction + aspect + why), most recent first. Near-duplicate stories are MERGED by default (each row
    = one story + `dup_count`); `collapse=false` for the raw feed. `limit` = how many (default 20, max 50)
    — heavily-covered assets have HUNDREDS, so keep it small + narrow. TIME-SCOPE with `from_`/`to` (ISO)
    or `window` ('90d','qtd','1y'); to COMPARE periods, call once per period. ⚠️ News starts 2026-01-01 —
    older ranges return nothing (no coverage, not 'no news'; price/volatility history goes back decades).
    🔵 BONDS/RATES: a specific tenor/rate (`US-2Y.GB`, `SOFR.MM`) with no news of its own returns the
    country's benchmark-10Y macro news tagged `scope:'curve_macro'` + `macro_source` — narrate those as
    curve-wide central-bank context, not tenor-specific."""
    tk, cf, _det = _ticker_arg(ticker, scope=_SCOPE_BROAD, country=country, context=context)  # 🆕 collapse find_stock (news = any asset)
    if cf: return cf
    ticker = tk
    # RAW endpoint (not the SDK StockNews model — it drops the `scope`/`macro_source` curve-macro tags a
    # bond/rate borrows from its benchmark 10Y); slim to narratable fields (which now keep those tags).
    params = {"direction": direction, "from": from_ or _win(window), "to": to, "limit": _lim(limit)}
    if collapse is not None:
        params["collapse"] = "true" if collapse else "false"
    params = {k: v for k, v in params.items() if v is not None}
    return _slim_articles(mdx()._get(f"/v1/stocks/{ticker}/news", params).data.get("results", []), _lim(limit))

@mcp.tool(title="Options Sentiment", annotations=_RO)
def options_sentiment(
    ticker: Annotated[Optional[str], _dt("A US-listed OPTIONABLE ticker (~547 names) or an index-ETF proxy (S&P→SPY, "
                                         "Nasdaq→QQQ). Non-US / uncovered → `covered:false` (not an error).")] = None,
    style: Annotated[str, _d("Narration style: `plain` (layperson, default) | `technical`.")] = "plain",
    as_of: Annotated[Optional[str], _d("As-of date YYYY-MM-DD (point-in-time positioning).")] = None,
    tickers: Annotated[Optional[List[str]], _d("Batch form — several tickers at once (instead of `ticker`).")] = None,
    dates: Annotated[Optional[List[str]], _d("Specific expiry dates YYYY-MM-DD to focus the read on.")] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """What the US OPTIONS MARKET is saying — the POSITIONING lens (~547 popular US optionable names,
    stocks + ETFs). Pairs with the news→impact read: for "how is <X> doing?" fetch THIS *and*
    `stock_impact`/`news_feed` and fuse them (news = what's happening + WHY; options = how the market is
    positioned — direction lean via put/call, fear/greed via skew, IV level, dealer-gamma stability,
    max-pain pinning, notable expiries). For a name the user HOLDS it shows how the market is hedging that
    position. Broad-INDEX question → pass the liquid ETF proxy: S&P 500→`SPY`, Nasdaq 100→`QQQ`, Dow→
    `DIA`, Russell 2000→`IWM`, 20y Treasuries→`TLT`, Gold→`GLD`. Tickers = bare US symbol or `SYMBOL.US`
    (`NVDA`/`NVDA.US`); US-only. `style` = `plain` (everyday language, default) | `technical`.

    TWO MODES:
    • SINGLE deep read — pass `ticker=<one>` (+ optional `as_of`). Returns the FULL narrative payload
      (horizons, buckets, per-signal `read`+`because`, `_guide`). Use for a focused "how is NVDA doing".
    • BATCH / COMPARE — pass `tickers=[...]` and/or `dates=[...]` → ONE call returns a COMPACT grid, one
      small row per (ticker × date) cell: `spot`, `positioning_score` ([-1,+1], + bullish), per-horizon
      positioning, and medium-term signal `reads`. THIS is how you answer "NVDA vs AAPL, last week vs
      this week" — do NOT fire the single tool N×M times. `dates=[]` (omit) → a single "latest" column.

    📅 HISTORICAL: `as_of`/`dates` = ISO date/timestamp; the snapshot AT-OR-BEFORE that instant. A bare
    date (`2026-07-15`) is read as END of that day. Every response carries `available_from`/`available_to`
    (the stored window); a cell whose date predates it comes back `covered:false` with the range — relay
    THAT honestly (say history only goes back to `available_from`), never invent an older reading.
    ⚠️ Narrate from `read`+`because` (or the batch `reads`); DON'T recompute, DON'T compare raw O/S or IV
    across assets, `baseline_pending`/`level` ≠ "unusual" (only a `_percentile`/`_rank` read flags
    unusual), and the VERDICT is YOURS (opana stops at interpretation). Not covered → `{covered:false}`:
    say options data isn't available and use the news/impact read instead — never fabricate."""
    batch = bool(tickers) or bool(dates)
    if batch:
        syms = list(tickers) if tickers else ([ticker] if ticker else [])
        cols = list(dates) if dates else ([as_of] if as_of else [])
        if not syms:
            return {"error": "batch mode needs `tickers=[...]` (and optionally `dates=[...]`)"}
        syms, cf, _det = _tickers_arg(syms, scope=_SCOPE_OPTIONABLE, context=context)  # 🆕 collapse find_stock (US-optionable)
        if cf: return cf
        body = {"tickers": syms, "as_of": [c for c in cols if c], "style": style}
        resp = mdx()._http._client.post("/v1/options/sentiment", json=body)
        _check(resp)
        return resp.json()
    if not ticker:
        return {"error": "pass `ticker=<symbol>` for a single read, or `tickers=[...]` for a batch compare"}
    tk, cf, _det = _ticker_arg(ticker, scope=_SCOPE_OPTIONABLE, context=context)       # 🆕 collapse find_stock
    if cf: return cf
    ticker = tk
    params = {"style": style}
    if as_of:
        params["as_of"] = as_of
    try:
        return mdx()._get(f"/v1/options/{ticker}/sentiment", params).data
    except NotFoundError as e:
        return {"covered": False, "symbol": ticker, "note": str(e) or (
            f"No options-sentiment for '{ticker}' — opana covers ~547 US-listed optionable names. Don't "
            "fabricate an options view; use news/impact for the read, and (if relevant) note options "
            "coverage isn't available for this name.")}

# ── Option-behavior STOCK scanner. There is NO find_oppattern tool — options_scan + screen_unified.options
#    resolve the behaviour (an exact key OR plain English) server-side via _resolve_oppattern (vector→Jev→gate).

@mcp.tool(title="Options Scan", annotations=_RO)
def options_scan(
    pattern: Annotated[str, _d("An options-behaviour pattern — an exact key OR plain English ('cheap implied vol', "
        "'crowd getting fearful', 'smart money piling in'); the server resolves it. CSV = AND-combine (intersect), "
        "e.g. 'iv_cheap,smart money buying'; the FIRST token owns the ranking. 🔴 ENGLISH.")],
    horizon: Annotated[Literal["short","long"], _d("`short` | `long` — which options horizon to read (default long = the "
        "positioning/conviction lens; short = the gamma/near-term lens).")] = "long",
    min_strength: Annotated[Optional[float], _d("Optional cutoff on the ranked axis / Δ — omit to let the "
        "scanner return the top-ranked names.")] = None,
    limit: Annotated[Optional[int], _d(_LIMIT)] = None,
) -> dict:
    """Find STOCKS by an options-behaviour pattern (opana lens) across the ~557 US optionable names — returns
    ranked UNDERLYINGS each with a plain-language `because` + `metrics` (value, and prev→delta for a trend/flip).
    STOCK scanner only: it does NOT pick option contracts/strikes/expiries (for one named stock's detail use
    `options_sentiment`). The `pattern` is a key OR plain English (the server resolves it) — its `temporal_mode`
    decides the read (level = now, rising/falling = ~2-week trend, flip = reversal). A `supported:'no'`/`'future'` pattern returns an empty
    list + an honest note (say so, don't substitute). US-capped — state that in the answer."""
    # 🆕 SERVER-SIDE resolution (collapse find_oppattern): each CSV token may be an exact key OR plain English —
    # resolve here. options_scan runs ONE options leg, so a compose/unsupported behaviour → honest guide (not a scan).
    toks = [t.strip() for t in str(pattern).split(",") if t.strip()]
    resolved_toks = []
    for t in toks:
        r = _resolve_oppattern(t)
        if r["status"] != "resolved":
            return {"needs_confirmation": True,
                    "confirm": {t: {"status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])}},
                    "_guide": "The options-behaviour term needs attention — pick the right `pattern` from its candidates "
                              "(or drop it if it isn't a scannable options behaviour), then RE-CALL options_scan with the chosen key."}
        if (r.get("exec_path") or "scan") != "scan" or str(r.get("supported")) == "no":
            return {"needs_confirmation": True,
                    "confirm": {t: {"status": "not_scannable", "reason": "not a single-leg options scan — it's a composite "
                                    "(needs another leg) or has no data", "exec_path": r.get("exec_path"), "supported": r.get("supported")}},
                    "_guide": "options_scan runs ONE options leg. For a composite behaviour (e.g. options-vs-price divergence) "
                              "use screen_unified's `options` leg; if it's unsupported, tell the user plainly — do not substitute."}
        resolved_toks.append(r.get("pattern"))
    pattern = ",".join(resolved_toks)
    body = {"pattern": pattern, "horizon": horizon, "limit": _lim(limit, default=15, ceiling=50, floor=1)}
    if min_strength is not None:
        body["min_strength"] = min_strength
    resp = mdx()._http._client.post("/v1/options/scan", json=body)
    _check(resp)
    return resp.json()

@mcp.tool(title="Theme Players", annotations=_RO)
def theme_players(theme: Annotated[str, _d("A megatrend theme — name/slug (resolved for you) or node id.")],
                  country: Annotated[Optional[str], _d("`all` (DEFAULT) = the whole cross-market roster — use this for 'who are the players in <theme>'. Or an ISO-2 market to scope to ONE venue. ⚠️ keyed by LISTING VENUE, not domicile: a foreign name lists under the market it TRADES on (Leonardo/Saab under GB via their LSE line, Novo under US/DE, Cameco under US) — so a home-country query (IT/SE/DK/CA) can return 0 even though the company IS a member. When in doubt use `all`.")] = "all",
                  exposure: Annotated[Optional[str], _d("Filter by exposure tier (e.g. `core`). Omit → all members.")] = None,
                  limit: Annotated[Optional[int], _d(_LIMIT)] = None) -> dict:
    """THE roster tool: investable MEMBER companies of a theme (curated membership). Rolls up sub-themes
    (a parent node returns its children's members too). Use this — not screen_stocks — for 'who are the
    players / real names in <theme>' (screen_stocks is a NEWS-ranked subset gated to news-epicenter members).
    `country='all'` (default) gives the complete cross-market list; an ISO-2 scopes to one trading venue.
    Different from top_entities (news-derived). `limit` = how many (default 20, max 50; big themes have many).
    Returns {stocks, count, total, note?} — if `total` > `count` it's a TOP SLICE: say so, don't present it
    as the full roster (raise `limit`)."""
    node, err = _theme_node(theme)
    if err: return err
    return _paged(mdx().theme(node).stocks(country=(country or "all"), exposure=exposure,
                                           max_items=_lim(limit)), key="stocks")

@mcp.tool(title="Private Movers", annotations=_RO)
def private_movers(theme: Annotated[str, _d("A megatrend theme — name/slug (resolved for you) or node id.")],
                   country: Annotated[Optional[str], _d(_COUNTRY_CSV)] = None,
                   limit: Annotated[Optional[int], _d(_LIMIT)] = None) -> dict:
    """Off-coverage / private companies the news moved within a theme — the 'beyond tickers' surface.
    `limit` = how many (default 20, max 50). Returns {companies, count, total, note?} — honor `note` when
    `total` > `count` (it's a top slice, not the whole set)."""
    node, err = _theme_node(theme)
    if err: return err
    return _paged(mdx().theme(node).off_coverage(country=country, max_items=_lim(limit)),
                  key="companies")

@mcp.tool(title="Company Relationships", annotations=_RO)
def relationships(ticker: Annotated[str, _dt(_TICKER)],
                  country: Annotated[Optional[str], _d(_TK_COUNTRY)] = None,
                  limit: Annotated[Optional[int], _d("Max competitors + peers each (default/cap per _lim).")] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """Competitors + peers of a company (news-derived relationship graph). `limit` caps EACH list
    (default 15, max 50). Each side carries `total`/`count`/`note` — a big `total` (peers often run to
    hundreds) means you're seeing a TOP slice; say so rather than implying it's the complete set."""
    tk, cf, _det = _ticker_arg(ticker, scope=_SCOPE_STOCK, country=country, context=context)  # 🆕 collapse find_stock (a company)
    if cf: return cf
    ticker = tk
    cli = mdx()
    ref = cli.stock(ticker)
    n = _lim(limit, default=15)
    # peers = the accurate CORE-based axes (peers?grouped=1, what the website shows), NOT the flat all-membership
    # list (which a secondary megatrend tag contaminates — CPALL → Visa/Mastercard).
    return {"competitors": _paged(ref.competitors(limit=n), key="items"),
            "peers": _grouped_peers(cli, ticker, n)}

@mcp.tool(title="List Megatrends", annotations=_RO)
def list_themes(query: Annotated[Optional[str], _d("Optional free-text filter over the megatrend taxonomy; omit → the browsable tree.")] = None) -> list:
    """Browse / discover the megatrend taxonomy (25 tier-1 families + sub-nodes) — resolve a theme id."""
    return _ser(mdx().megatrends().to_list())

@mcp.tool(title="List Portfolios", annotations=_RO)
def list_portfolios() -> dict:
    """List the user's OWN portfolios (id, name, base_currency, account_type, nav, total_return_pct,
    unrealized_pnl, position_count, …) so you can pick one to analyze. Call this FIRST whenever the user
    says 'my portfolio' without a number — show the names, then pass the chosen `id` to
    `portfolio_context`. Owner-scoped: only ever the user's own portfolios.
    If `count` is 0 (they own none), the response carries a `note` with a create link — relay THAT
    (invite them to create a portfolio) instead of saying an empty 'you have no portfolios'."""
    return mdx().portfolios()

@mcp.tool(title="Portfolio Context", annotations=_RO)
def portfolio_context(portfolio_id: Annotated[int, _d(_PID)],
                      from_: Annotated[Optional[str], _d("Window start YYYY-MM-DD — re-scopes performance/attribution/composition together.")] = None,
                      to: Annotated[Optional[str], _d("Window end YYYY-MM-DD.")] = None,
                      window: Annotated[Optional[str], _d("Re-scope perf+attribution+composition to a period: `7d`/…/`ytd`. Omit → lifetime + recent(12mo).")] = None,
                      snapshots: Annotated[Optional[Literal["year","quarter","month","week","day","off"]], _d("Point-in-time composition cadence: `year|quarter|month|week|day|off` (default quarter); auto-coarsens over long spans.")] = None) -> dict:
    """An LLM-ready snapshot of ONE of the user's OWN portfolios (owner-scoped) — analyze it directly.
    NO window → default: `meta` · `summary` · a `lifetime`(all-time) + `recent`(~12mo) block, EACH with
    `performance` (return/cagr/sharpe/sortino/calmar/drawdown/vol/win_rate) + `attribution` · `positions`
    · `closed_positions` (realized_pnl) · `composition` (point-in-time holdings) · `allocation` ·
    `concentration` (HHI) · `inferred_behavior` · `flags`. `portfolio_id` from `list_portfolios`; 404 if
    not the user's.

    TIME WINDOW — `from_`/`to` (ISO) or `window` (`7d|30d|90d|180d|1y|mtd|qtd|ytd`): REPLACES lifetime+
    recent with ONE `window` block (that span's `performance` + `attribution` + `nav_trend`) and scopes
    `composition` to match. So ANY period's return + drivers is answerable. `snapshots` = composition
    granularity only (`year|quarter|month|week|day|off`).
    🔴 MANDATORY for period questions: the default / `lifetime` / `recent` blocks DO NOT contain the
    performance or attribution of an arbitrary period (e.g. Q1-2025, "H1 2024"). To answer ANY specific
    period — or to COMPARE periods (Q1/25 vs Q1/26, 2023 vs 2025) — you MUST call this tool AGAIN with
    `from_`/`to` (or `window`) for EACH period, then compare the returned `window` blocks. NEVER derive a
    period's return/sharpe/drawdown/attribution from the default view — those numbers aren't in it; making
    them up is a hard error. If you haven't fetched a period's window, say you need to fetch it, don't guess.

    HOW TO ANALYZE (research-analyst framing — see marketdx://policy):
    • Lead with the sharpest thing: a non-empty `flag`, or the biggest concentration / drawdown / tilt.
    • "What drove the return / drawdown / strengths & weaknesses" (for the default OR a window) → read
      `attribution.contributors[]` (per-holding `pnl_contribution` + `pct_of_nav_change` + `held` window;
      reconciles to `nav_change` to the cent, INCLUDES since-sold names). Don't estimate it yourself.
    • "What did I hold on date X / how did the book evolve" → `composition` (set `snapshots` + a window).
    • ⚠️ TRUST THE EDGE NOTES, never fabricate: a window before the portfolio's `inception_date` returns
      `window.empty=true` + a note (or clamped) — say "the portfolio didn't exist then". If
      `composition.coarsened` is true, the step was widened to stay bounded — for finer, narrow the window.
    • NEWS-AWARE: fuse `stock_impact` / `news_feed`/`search_news` on the holdings' `theme` paths for the
      WHY (⚠️ news only covers 2026+; portfolio history goes back to inception, further than news).
    • Facts, not advice. Observe; do NOT tell them to buy/sell/rebalance/time — hand the judgment back."""
    return mdx().portfolio_context(portfolio_id, from_=from_, to=to, window=window, snapshots=snapshots)

# WHICH surface authored a note. Historically read from the MCP `clientInfo` handshake — but under
# stateless HTTP (required for horizontal scaling) the handshake context is not available at tool-call
# time, so the caller declares it via the `agent` enum on write_note. A CLOSED enum (not a free string)
# keeps the value clean & queryable — "Claude Code" always maps to the same token, no "Claude"/"claude"
# drift. Unknown/other clients pick "Other". clientInfo stays as a best-effort fallback when present.
AgentName = Literal["Claude", "Claude Code", "Claude Coworks", "ChatGPT", "Codex", "Gemini", "Other"]
_AGENT_ENUM_TOKEN = {
    "Claude": "claude", "Claude Code": "claude-code", "Claude Coworks": "claude-coworks",
    "ChatGPT": "chatgpt", "Codex": "codex", "Gemini": "gemini", "Other": "other",
}
_AGENT_ALIASES = (("claude", "claude"), ("chatgpt", "chatgpt"), ("openai", "chatgpt"),
                  ("cursor", "cursor"), ("marketdx", "marketdx-web"))

def _client_agent(ctx: Optional[Context]) -> Optional[str]:
    try:
        raw = (ctx.session.client_params.clientInfo.name or "").strip().lower()
    except Exception:
        return None
    if not raw:
        return None
    for needle, token in _AGENT_ALIASES:
        if needle in raw:
            return token
    slug = "".join(c if (c.isalnum() or c in "._-") else "-" for c in raw)[:40].strip("-")
    return slug or None

def _resolve_agent(agent: Optional[str], ctx: Optional[Context]) -> Optional[str]:
    """Prefer the caller-declared enum (stable token), else fall back to clientInfo (when a session
    is present), else None. Stateless transport → the enum is the only reliable source."""
    if agent:
        return _AGENT_ENUM_TOKEN.get(agent, "other")
    return _client_agent(ctx)

@mcp.tool(title="Save Note", annotations=_WRITE)
def write_note(subject: Annotated[str, _d("Short title / subject line of the note.")],
               body: Annotated[str, _d("The note's full text in MARKDOWN — the distilled answer/observation/thesis to "
                   "persist. PRESERVE the structure of your answer: any numeric / tabular data goes in a markdown TABLE "
                   "(pipe syntax `| col | col |`), NEVER flattened into a paragraph of numbers; use headings (##) for "
                   "sections and bullet lists for points. If you showed the user a table, the note keeps that table.")],
               summary: Annotated[Optional[str], _d("One-line summary (shown when the note is collapsed).")] = None,
               note_type: Annotated[Optional[Literal["reference","tracking","thesis","decision"]], _d("`reference` (concept/understanding) | `tracking` (dated market read) | `thesis` | `decision`.")] = None,
               category: Annotated[Optional[str], _d("Optional free-text category.")] = None,
               tags: Annotated[Optional[List[str]], _d("Free-text tags for retrieval.")] = None,
               stocks: Annotated[Optional[List[str]], _d("PRIMARY stocks/assets the note is ABOUT — an exact MarketDX ticker OR a plain NAME the SERVER resolves (any asset class; an ambiguous name → reconfirm). ⚠️ A COMMODITY discussed via the trade tools has only an HS code (rice→1006), NOT a ticker — just put the NAME here ('rice'→resolved to RICE.COMM) so the note links to the commodity.")] = None,
               mentioned_stocks: Annotated[Optional[List[str]], _d("Secondary tickers merely referenced (a peer named in passing).")] = None,
               megatrend_ids: Annotated[Optional[List[int]], _d("ADVANCED — raw megatrend node id(s) if you already hold one (e.g. a theme tool's `megatrend.id`). Normally just name the theme in `gics` and the server routes it to a megatrend.")] = None,
               gics: Annotated[Optional[List[str]], _d("The note's INDUSTRY/SECTOR or THEME — a GICS code OR plain English ('banks', 'semiconductors', 'AI'); the server resolves each and routes a curated theme to a megatrend link. (Derived free if the note names representative stocks.)")] = None,
               portfolio_id: Annotated[Optional[int], _d("Link the note to one of the user's portfolios, if relevant.")] = None,
               agent: Annotated[Optional[AgentName], _d("Which app is writing the note — set to the surface you run in "
                   "(e.g. `claude` | `chatgpt` | `marketdx-web`); the server falls back to the connection's client info.")] = None,
               ctx: Context = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """🔴 WRITE — save a NOTE to the user's account (this PERSISTS data; it is NOT a read/lookup). Typical
    flow: FIRST give the user your complete answer as usual, THEN — as the final step of the turn — call
    `write_note` once to keep it.

    🔴 IF YOUR ANSWER CONTAINED A TABLE / NUMERIC COMPARISON, keep it as a MARKDOWN table in `body` — lead with
    the table, do NOT re-narrate the numbers into prose. Saving a figures answer as a wall of prose is the #1
    note-quality failure; preserving structure OUTRANKS "distilling into a paragraph". (The figures are extracted
    from these markdown tables later for charts — so a clean table with clear headers is what makes that possible.)

    CONTENT:
      • `subject` — a short title you compose (≤200 chars).
      • `body` — the substance to keep, in MARKDOWN. Make it stand alone, but PRESERVE the structure you showed:
        every TABLE stays a markdown table (pipe syntax), headings stay headings. "Distill" = trim wording, NOT
        collapse a table into a sentence. If the answer led with a table, the body leads with the same table.
        Use clear ABSOLUTE column headers (`FY2025`, not `Latest`/`FY-1`) so the figures stay unambiguous.
      • `summary` — a 1–2 sentence gist for scanning later.
      • `note_type` — one of `thesis` / `reference` / `snapshot` / `decision` / `watchlist`.
      • `category` — a free bucket, e.g. `research` / `portfolio` / `idea`.
      • `tags` — a few keywords for retrieval.

    ENTITY LINKS — this is what makes the note findable later by interest and joinable to the graph, so
    fill them whenever the note touches specific things. The server RESOLVES names for you (it canonicalizes and
    links them, and reports what linked) — pass plain names, or reuse identifiers you already hold this turn:
      • `stocks` — the stock(s)/asset(s) this note is ABOUT (its subjects) — an exact ticker (`005930.KO`,
        `AAPL`) OR a plain NAME the server resolves (an ambiguous name comes back as a reconfirm to pick from).
      • `mentioned_stocks` — stocks merely referenced, not the focus (same name-or-ticker resolution).
      • `gics` — the note's INDUSTRY/SECTOR or THEME — a code OR plain English ('banks', 'semiconductors', 'AI');
        the server resolves each and routes a curated theme to a megatrend link.
      • `megatrend_ids` — ADVANCED: a raw node id you already hold (a theme tool's `megatrend.id`); normally you
        don't set this — name the theme in `gics` instead.
      • `portfolio_id` — if the note is about one of the user's portfolios (from `list_portfolios`).

    🧭 LINK THE NOTE'S HOME — the theme/sector, not just the stocks. If the note is about a TREND/tech/mechanism
    ("what is HBM", "solid-state batteries") or an established INDUSTRY/SECTOR ("retail", "airlines", "pharma"),
    put the word(s) straight in `gics` (plain English — the server resolves each and routes a theme→megatrend).
    A note whose subject is a trend or a sector, saved with EMPTY `gics`, means you SKIPPED this. The only correct
    empties: a single-stock note (stocks only) or a general concept with no home (P/E, EBITDA — don't force it;
    tags/body still make it findable by semantic search).

    WHEN TO SAVE — this is the investor's knowledge base; CAPTURE substantive investment content generously
    (reference/understanding, a dated market-read WITH its 'why', a thesis/decision, curated research). Value
    is realized on RETRIEVAL, so lean toward keeping. SKIP only the noise floor: chit-chat/thanks, trivial
    lookups ("what's the ticker?"), or off-topic non-investment content (save that only if explicitly asked).
    An explicit "save this / จดไว้" → always save. Otherwise, if the content is note-worthy, briefly OFFER to
    keep it — don't nag on every turn, and don't save pure filler.

    🏷️ `agent` — ALWAYS set this to the app you are running in, chosen from the fixed list:
    `Claude` (Claude apps / claude.ai / Desktop), `Claude Code`, `Claude Coworks`, `ChatGPT`, `Codex`,
    `Gemini`, or `Other` (anything not listed). It stamps WHICH surface authored the note (provenance in
    the user's knowledge base). Pick the single closest match; if genuinely unsure, use `Other`. Do not
    invent values — only these are accepted.

    Owner-scoped. Returns `{id, created_at, linked}` where `linked` confirms what was tied to the graph
    (resolved ids + any `unresolved` names)."""
    if stocks:  # 🆕 collapse find_stock — a NAME or an exact ticker; ANY pending → reconfirm before saving
        stocks, _cf, _ = _tickers_arg(stocks, scope=_SCOPE_BROAD, context=context)
        if _cf: return _cf
    if mentioned_stocks:
        mentioned_stocks, _cf, _ = _tickers_arg(mentioned_stocks, scope=_SCOPE_BROAD, context=context)
        if _cf: return _cf
    if gics:  # UNIFIED: gics tags may be codes OR plain English → resolve; a THEME concept becomes a megatrend link
        _g, _t, _cf, _ = _scope_resolve(gics)
        if _cf: return _cf
        gics = _g or None
        if _t:
            megatrend_ids = (megatrend_ids or []) + [x for x in _t if x not in (megatrend_ids or [])]
    payload = {k: v for k, v in {"subject": subject, "body": body, "summary": summary,
                                 "type": note_type, "category": category, "tags": tags,
                                 "stocks": stocks, "mentioned_stocks": mentioned_stocks,
                                 "megatrend_ids": megatrend_ids, "gics_codes": gics,
                                 "portfolio_id": portfolio_id,
                                 "agent": _resolve_agent(agent, ctx)}.items() if v is not None}
    r = mdx()._http._client.post("/v1/notes", json=payload)
    if r.is_success:
        return r.json()
    try:
        j = r.json(); msg = j.get("error") or r.text; note = j.get("note")
    except Exception:
        msg = r.text or f"HTTP {r.status_code}"; note = None
    raise ValueError(f"save failed: {msg}{' — ' + note if note else ''}")

@mcp.tool(title="My Notes", annotations=_RO)
def query_notes(q: Annotated[Optional[str], _d("Semantic query text — recall notes by MEANING (cross-language).")] = None,
                stock: Annotated[Optional[str], _d("Filter to notes about a ticker (name/ticker → resolved).")] = None,
                theme: Annotated[Optional[str], _d("Filter to a theme (name → megatrend, incl. subtree rollup).")] = None,
                gics: Annotated[Optional[str], _d("GICS code filter.")] = None,
                tag: Annotated[Optional[str], _d("Tag filter.")] = None,
                note_type: Annotated[Optional[Literal["reference","tracking","thesis","decision"]], _d("Filter by type (reference/tracking/thesis/decision).")] = None,
                since: Annotated[Optional[str], _d("Only notes since this date/window (e.g. `30d` or YYYY-MM-DD).")] = None,
                limit: Annotated[Optional[int], _d(_LIMIT)] = None,
                relation: Annotated[Optional[str], _d("With `stock=`: `direct` (note ABOUT it) | `indirect` (merely referenced) | `any` (default).")] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """Recall the USER'S OWN saved notes — their personal investment knowledge base (owner-scoped, only
    ever their notes). Two combinable ways:
      • SEMANTIC recall via `q` — natural language ("what did I say about foundry manufacturing?"); results
        are ranked by MEANING with a `similarity` score (cross-language OK).
      • Structured filters: `stock` (a ticker → their notes about it), `theme` (a sector/trend NAME →
        resolved to the megatrend, subtree included), `gics` (6-digit code), `tag`, `note_type`
        (thesis/reference/snapshot/decision/watchlist), `since` (e.g. '30d').
    📌 `stock` + `relation` (direct|indirect|any, default any) splits how a note relates to that ticker —
    same idea as newsfeed direct/indirect: `direct` = the note is ABOUT it (a subject); `indirect` = it's
    only REFERENCED (e.g. a peer named in a note about ANOTHER stock — a "NVDA vs peers" note surfaces
    under AMD as indirect). Every returned note carries a `relation` label when you filter by `stock`, so
    you can say "1 note about AMD + 1 that only mentions it". Use `relation="direct"` for "notes really
    about X".
    Returns note SUMMARIES + linked entities + `similarity` — NOT the full body (call `get_note(id)` for
    that). `limit` default 10 (max 50).
    🔴 FUSE personal + live: when the user asks about something they've likely noted, pair this with the
    live read — e.g. `asset_pulse(NVDA)` AND "your NVDA thesis from last week said …". That personal-
    knowledge + live-graph combination is the whole point of the notes layer."""
    params: dict = {}
    if q:
        params["q"] = q
    if stock:  # 🆕 collapse find_stock — a name/ticker filter → resolved (best-effort; raw passthrough if not unique)
        _tk, _cf, _ = _ticker_arg(stock, scope=_SCOPE_BROAD, context=context)
        params["stock"] = _tk or stock
    if relation:
        params["relation"] = relation
    if theme:  # UNIFIED: a theme name → megatrend node (best-effort filter; skip if not a theme)
        _n, _ = _theme_node(theme)
        if _n: params["megatrend"] = _n
    if gics:  # UNIFIED: gics code OR plain English; a theme concept narrows by megatrend
        _g, _t, _cf, _ = _scope_resolve(gics)
        if _cf: return _cf
        if _g: params["gics"] = ",".join(_g)
        if _t and "megatrend" not in params: params["megatrend"] = _t[0]
    if tag:
        params["tag"] = tag
    if note_type:
        params["type"] = note_type
    if since:
        params["since"] = since
    params["limit"] = _lim(limit, default=10, ceiling=50)
    return mdx()._get("/v1/notes", params).data

@mcp.tool(title="Read Note", annotations=_RO)
def get_note(note_id: Annotated[int, _d("The note's id (from query_notes results). Owner-scoped → 404 if not yours.")]) -> dict:
    """The FULL saved note (including its `body`) by id — owner-scoped. Use after `query_notes` when you
    need the complete content, not just the summary."""
    return mdx()._get(f"/v1/notes/{note_id}", {}).data

# ── PLAYLISTS — a user-curated set of STOCKS they follow, which drives their news Feed ─────────
def _pl_write(method: str, path: str, payload: Optional[dict] = None) -> dict:
    c = mdx()._http._client
    r = c.request(method, path, json=payload) if payload is not None else c.request(method, path)
    if r.is_success:
        try:
            return r.json()
        except Exception:
            return {}
    try:
        j = r.json(); msg = j.get("error") or r.text
    except Exception:
        msg = r.text or f"HTTP {r.status_code}"
    raise ValueError(f"playlist op failed: {msg}")

@mcp.tool(title="List Playlists", annotations=_RO)
def list_playlists() -> dict:
    """List the user's OWN feed playlists (id, name, emoji, item_count, items[{kind,ref_id,label}]).
    🔴 Call this FIRST whenever the user refers to a playlist BY NAME ("add X to My Tech List") — you
    match the (possibly mistyped / mis-spaced) name against the REAL names yourself. If the user didn't
    say WHICH and they own more than one, ASK which one (show the names). If they own NONE, offer to
    create one. Owner-scoped — only ever the user's own playlists. A playlist drives their news Feed."""
    return mdx()._get("/v1/playlists", {}).data

@mcp.tool(title="Create Playlist", annotations=_WRITE)
def create_playlist(name: Annotated[str, _d("The new playlist's display name.")],
                    emoji: Annotated[Optional[str], _d("Optional emoji icon for the playlist.")] = None) -> dict:
    """🔴 WRITE — create a new feed playlist (owner-scoped). Do NOT auto-create from a possible typo:
    call `list_playlists` FIRST and only create when the name genuinely doesn't exist, or the user
    confirms a new one. Returns the created playlist {id, name, …}."""
    return _pl_write("POST", "/v1/playlists",
                     {k: v for k, v in {"name": name, "emoji": emoji}.items() if v is not None})

@mcp.tool(title="Add to Playlist", annotations=_WRITE)
def add_to_playlist(playlist_id: Annotated[int, _d("The playlist's id (from list_playlists).")],
                    tickers: Annotated[List[str], _d("Stocks to add — an EXACT MarketDX ticker (`AAPL.US`, `BTC-USD.CC`) "
                        "OR a plain NAME/symbol ('Apple', 'ซัมซุง', 'btcusd') which the SERVER resolves for you (any "
                        "asset class). An ambiguous/same-name-across-markets one comes back as a reconfirm to pick from.")],
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """🔴 WRITE — add one or more STOCKS/assets to a playlist (batch, idempotent). Each entry may be an exact
    MarketDX ticker OR a name/symbol the server resolves (any asset class: stock/ETF/commodity/crypto/FX). An
    ambiguous name (e.g. same name across markets) returns a `needs_confirmation` reconfirm — pick the exact ticker
    and re-call. `playlist_id` from `list_playlists`. Re-adding an existing ticker is a harmless no-op. Returns
    `{added, skipped, item_count}` — ⚠️ RELAY any `skipped` to the user; never drop it silently."""
    tks, cf, _det = _tickers_arg(tickers, scope=_SCOPE_BROAD, context=context)  # 🆕 collapse find_stock (playlists hold any asset)
    if cf: return cf
    items = [{"kind": "stock", "ref_id": t, "label": t} for t in tks]
    return _pl_write("POST", f"/v1/playlists/{playlist_id}/items", {"items": items})

@mcp.tool(title="Remove from Playlist", annotations=_WRITE)
def remove_from_playlist(playlist_id: Annotated[int, _d("The playlist's id.")],
                         tickers: Annotated[List[str], _d("MarketDX tickers to remove from the playlist.")]) -> dict:
    """🔴 WRITE — remove one or more stocks (by ticker) from a playlist (batch). `playlist_id` from
    `list_playlists`. Returns `{removed, not_found, item_count}` — relay `not_found` (a ticker that
    wasn't in the playlist) to the user."""
    items = [{"kind": "stock", "ref_id": t} for t in tickers]
    return _pl_write("DELETE", f"/v1/playlists/{playlist_id}/items", {"items": items})

# NB: portfolio_card / portfolio_nav IMAGE tools (rendered PNG via /v1/portfolios/:id/{card,nav}) were
# built + removed 2026-07-17 — Claude custom connectors DON'T render inline tool-result images (same gate
# as MCP Apps UI), so a 120KB PNG just burned context without displaying. The API endpoints stay; re-add
# these tools if a client gains connector-image rendering or via a Connector Directory listing.

# ── COMPOSITE tools (whole multi-step pipeline server-side, ONE call) ─────────
# Composites bundle several endpoints → keep each row APPROPRIATELY light so the bundle stays
# context-friendly (the raw impact row carries a huge `raw` blob; options a big per_bucket audit).
_ART_KEEP = ("title", "brief_text", "url", "publisher", "article_published_at", "impact", "news_types",
             "impact_score", "dup_count", "trend", "trend_id", "scope", "macro_source")
# NOTE: the news-api emits the date as `article_published_at` (not `published_at`) and the per-article
# DIRECTION lives inside `impact.net_direction` (there is no free-text `why`/`reason` field — the "why" is
# `brief_text` + `impact.aspects`). Keep the real key names so the date isn't silently dropped.
def _slim_articles(rows, n=6):
    """Keep only the narratable fields of an impact-article row (drop the big `raw` blob + ids) + cap N.
    Renames `article_published_at` → `published_at` so the date field name is consistent with search_news
    and the rest of the API (asset_pulse used to expose the raw longer name)."""
    out = []
    for a in (rows or [])[:n]:
        d = {k: a[k] for k in _ART_KEEP if k in a}
        if "article_published_at" in d:
            d["published_at"] = d.pop("article_published_at")
        out.append(d)
    return out

def _codes(v):
    """Coerce a `codes` argument to a list — accept a real list, a bare single code, or a comma-joined
    string (LLM-friendly: a model that passes "8542" or "0207,0203" instead of ["8542"] still works)."""
    if v is None:
        return None
    if isinstance(v, str):
        return [c.strip() for c in v.split(",") if c.strip()]
    return v

_REL_KEEP = ("name", "symbol", "exchange", "country", "gic_code")
def _slim_relations(rows, n=5):
    """Keep just enough of a competitor/peer to judge sector-overlap (name/symbol/exchange/country)."""
    return [{k: c[k] for k in _REL_KEEP if c.get(k) is not None} for c in (rows or [])[:n]]

def _grouped_peers(cli, ticker, n=6):
    """The ACCURATE peers the website shows — `peers?grouped=1` (CORE-based axes: leaders / home / trending),
    so a company's SECONDARY megatrend tag can't drag in unrelated names (CPALL no longer returns Visa/MA).
    Flattened + dedup'd into one list. The plain `ref.peers()` uses ALL memberships and gets contaminated."""
    try:
        g = cli._get(f"/v1/stocks/{ticker}/peers", {"grouped": 1}).data or {}
        groups = g.get("groups", {}) or {}
        seen, out = set(), []
        for axis in ("leaders", "home", "trending"):
            for x in (groups.get(axis) or []):
                sym = x.get("symbol") or x.get("ticker")
                if sym and sym not in seen:
                    seen.add(sym); out.append(x)
        return out[:n]
    except Exception:
        return []

def _brief_slim(b):
    """Keep a brief's breadth SUBSTANCE (pulse summary + winners/losers + top_stories) for a multi-angle
    bundle; drop the heavy chart-series + aspect_heatmap + top_entities/top_assets (get the full brief via
    `brief`/`theme_summary`)."""
    if not isinstance(b, dict):
        return b
    out = {k: b[k] for k in ("applied_scope", "window", "winners", "losers", "top_stories") if k in b}
    p = b.get("pulse") or {}
    out["pulse"] = {k: p[k] for k in ("story_count", "net_direction", "pos_share") if k in p}
    return out

def _slim_context(ctx: dict) -> dict:
    """Drop CHART-only / redundant bulk from a portfolio_context for the pulse bundle — the analytical
    substance (summary, performance, attribution, positions, allocation, concentration, flags, meta,
    closed_positions) stays; only the raw nav sparklines, per-position value_trend, and point-in-time
    `composition` snapshots go (call `portfolio_context` if you need those)."""
    c = dict(ctx)
    c.pop("composition", None)
    for blk in ("lifetime", "recent", "window"):
        if isinstance(c.get(blk), dict):
            c[blk] = {k: v for k, v in c[blk].items() if k not in ("nav", "nav_trend")}
    if isinstance(c.get("positions"), list):
        c["positions"] = [{k: v for k, v in p.items() if k != "value_trend"} for p in c["positions"]]
    return c

@mcp.tool(title="Asset Pulse", annotations=_RO)
def asset_pulse(ticker: Annotated[str, _dt(_TICKER + " ⚠️ a COMPANY/ETF/index-ETF/crypto — for a COMMODITY use "
                                   "commodity_pulse, for a BOND/RATE use bond_pulse.")],
                window: Annotated[Optional[str], _d(_WINDOW)] = None,
                limit: Annotated[Optional[int], _d(_LIMIT)] = None,
                country: Annotated[Optional[str], _d(_TK_COUNTRY)] = None,
                style: Annotated[str, _d("Options narration style: `plain` (layperson, default) | `technical`.")] = "plain",
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """⭐ THE tool for "how is <ticker> doing right now?" — gathers EVERY lens in ONE call so the answer
    is never half-informed (the whole point: you decide ONCE, the server guarantees completeness). Fans
    out server-side, in parallel, to:
      • `price` — the LEVEL + how it's moving: windowed changes (1w→1y), 52-week range, drawdown from the
        peak, realized-vol percentile (is today's vol high vs its OWN year), volume conviction — digested
        with plain-language `*_read` labels (split/div-adjusted). The number that makes news+options actionable.
      • `impact` — the ticker's news→impact feed (what moved it + direction + aspect + WHY; == stock_impact)
      • `options` — the US options market's positioning (fear/greed via skew, put/call lean, dealer-gamma
        stability, max-pain pinning, notable expiries; == options_sentiment)
      • `relationships` — competitors + peers (== relationships) → tells you if a move is SECTOR-WIDE
        (rivals/peers moving too) or IDIOSYNCRATIC (this name only)
    PREFER THIS over calling stock_impact / options_sentiment separately for any "how is X doing / what's
    up with X / X update" ask — it guarantees BOTH lenses are present; use the individual tools only to
    DRILL into one afterwards. `ticker` = a company (`AAPL` / `NVDA.US`) or a market INDEX via its liquid
    ETF proxy (S&P 500→`SPY`, Nasdaq 100→`QQQ`, Dow→`DIA`, Russell 2000→`IWM`, 20y UST→`TLT`, Gold→`GLD`).
    `window` = 7d/30d/90d/180d/1y/mtd/qtd/ytd — scopes the news recency. Then SYNTHESIZE a multi-lens read:
    the sharpest insight is often where NEWS and OPTIONS POSITIONING **diverge** (e.g. calm news but
    options paying up for downside). Narrate `options` from ITS `_guide` (read+because, no recompute, no
    cross-asset O/S·IV compare, verdict is yours). `options.covered=false` (non-US / not in the ~547) →
    answer from `impact` and say options isn't available; never fabricate positioning. If the user HOLDS
    the ticker, tie the read to their position (facts, not advice)."""
    tk, cf, _det = _ticker_arg(ticker, scope=_SCOPE_ASSET, country=country, context=context)  # 🆕 collapse find_stock (company/ETF/crypto)
    if cf: return cf
    ticker = tk
    cli = mdx()  # bind the caller's client in THIS thread — the contextvar key isn't set inside workers
    frm = _win(window)
    def _impact():
        try:  # RAW endpoint (not the SDK StockNews model, which drops `scope`/`macro_source` — the
            params = {"collapse": "true", "limit": _lim(limit, default=6)}  # curve-macro fallback tags)
            if frm:
                params["from"] = frm
            rows = cli._get(f"/v1/stocks/{ticker}/news", params).data.get("results", [])
            return {"articles": _slim_articles(rows, 6)}
        except Exception as e:  # unknown ticker / no impact rows — degrade, don't kill the bundle
            return {"error": str(e), "articles": []}
    def _options():
        try:  # single asset → return options FULL (it's only ~10KB; keeps _guide.audience so the plain-
            return cli._get(f"/v1/options/{ticker}/sentiment", {"style": style}).data  # language mandate survives
        except NotFoundError as e:
            return {"covered": False, "note": str(e)}
        except Exception as e:
            return {"covered": False, "note": f"options lookup failed: {e}"}
    def _relations():
        try:
            ref = cli.stock(ticker)
            # peers = the accurate CORE axes (grouped=1) — a secondary megatrend tag can't drag in noise.
            return {"competitors": _slim_relations(_ser(ref.competitors(limit=5).to_list())),
                    "peers": _slim_relations(_grouped_peers(cli, ticker, 6))}
        except Exception as e:
            return {"error": str(e), "competitors": [], "peers": []}
    def _price():
        try:  # the LEVEL lens — digested, already-narrated price features (1w→1y changes, 52w range,
            return cli._get(f"/v1/stocks/{ticker}/prices", {}).data  # drawdown, realized-vol percentile, volume conviction; *_read labels)
        except NotFoundError as e:
            return {"note": f"no price history: {e}"}
        except Exception as e:  # endpoint not shipped yet / lookup failed → degrade, don't kill the bundle
            return {"note": f"price unavailable: {e}"}
    def _fin():  # embed the fundamentals summary (deterministic — so the model gets financials without a
        try:  # 2nd call). EQUITY ONLY: an ETF/crypto/index/commodity has no company financials → None (expected).
            d = cli._get("/v1/financials", {"ticker": ticker, "summary": "1"}).data
            cos = (d or {}).get("companies") or []
            c = cos[0] if cos else None
            if not c or not c.get("ok"):
                return None
            out = {k: c.get(k) for k in ("revenue", "revenue_growth_yoy", "net_margin", "gross_margin",
                    "operating_margin", "net_income", "net_income_growth_yoy", "free_cash_flow",
                    "operating_cash_flow", "total_assets", "currency", "as_of", "source", "read")}
            sg = c.get("signals")   # abnormality/pattern flags (trend/outlier/contradiction) — the "เอ๊ะ"
            if sg and sg.get("count"):
                out["signals"] = {"headline": sg.get("headline"), "top": (sg.get("signals") or [])[:4], "count": sg.get("count")}
            return out
        except Exception:
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        fi, fo, fr, fp, ff = ex.submit(_impact), ex.submit(_options), ex.submit(_relations), ex.submit(_price), ex.submit(_fin)
        impact, options, relations, price, fundamentals = fi.result(), fo.result(), fr.result(), fp.result(), ff.result()
    return {
        "ticker": ticker, "window": window or "recent",
        "price": price, "impact": impact, "options": options, "relationships": relations,
        "fundamentals": fundamentals,
        "_guide": ("Synthesize a MULTI-LENS read — do NOT answer from one lens. `price` = the LEVEL + how "
                   "it's moving (windowed changes, how far below the 52w peak = `drawdown_from_52w_high_pct`, "
                   "is today's vol high vs its OWN year = `realized_vol_percentile_1y`, accumulation vs "
                   "distribution = `up_down_volume_ratio_1mo`); `impact` = what the news did (+ why); "
                   "`options` = how the options market is positioned; `relationships` = is the move "
                   "SECTOR-WIDE (peers/rivals moving too) or IDIOSYNCRATIC? 💰 `fundamentals` (EQUITY only — "
                   "null for an ETF/index/crypto is EXPECTED, don't flag it) = the company's compact financial "
                   "health (revenue + YoY growth, margins, free cash flow); QUOTE its `read`, and tie quality/"
                   "valuation to the price+news picture (the sharp insight is often a DIVERGENCE — strong price "
                   "but shrinking margins, or a selloff despite growing FCF). `fundamentals.signals` = "
                   "auto-detected abnormality/pattern flags (multi-year trends, outlier jumps, accounting "
                   "CONTRADICTIONS like receivables outpacing revenue) — LEAD with `signals.headline` if present "
                   "and narrate the top flags in plain words (they're high-recall — judge which actually matter). "
                   "It's already here — do NOT make a separate `financials` call unless the user wants a deep/compare or full statements. "
                   "Lead with where the lenses AGREE or DIVERGE (divergence is the insight — e.g. strong news but price −14% from the peak). "
                   "QUOTE price `*_read` labels directly (pre-computed, don't re-derive). 🔴 EXPLAIN "
                   "`options` FOR A NON-EXPERT (follow the options payload's own `_guide.audience`) — "
                   "translate EVERY options term (put/call, IV, gamma, skew, max-pain, O/S) into plain "
                   "everyday words, keep a number only if it helps a layperson; do NOT dump jargon. If "
                   "`options.covered` is false, answer from `impact`+`price`; `price.note` present → say "
                   "price isn't available; never fabricate. 🔵 If `price.metric_kind` == 'yield' (a `.GB` "
                   "bond yield or `.MM` rate): narrate the move in BASIS POINTS (`change_bps`), NOT % (a % "
                   "of a yield is sign-inverted); use `price_proxy_pct`/`mod_duration` for a bond-PRICE "
                   "estimate (label it an estimate); yield↑ ⇒ bond price↓. A yield has NO options/PE/market-"
                   "cap, so `options.covered=false` here is EXPECTED — don't flag it as a gap, just read "
                   "price + news. If an `impact` article carries `scope:'curve_macro'`, it was BORROWED from "
                   "the country's benchmark 10Y (`macro_source`) because this specific tenor/rate has no news "
                   "of its own — narrate it as curve-wide central-bank/macro context, NOT specific to this "
                   "tenor. 🌐 TRADE LENS: `price` also carries `related_assets` (materiality-weighted COMM/FX "
                   "links — `channel` = the angle: output_price=its product, input_cost=a cost, demand=a "
                   "backdrop; not listed = not material, don't invent a supply chain), `revenue_by_region` "
                   "(where it sells — the WHERE for trade + the cross-border gate) and `currency_exposures`. "
                   "For a GOODS/exporter or a policy/tariff-exposed name, you MAY deepen with the trade tools "
                   "(the trade tools search_trade/top_traders/trade_balance): enumerate the firm's material product "
                   "lines from `description`, pass each product concept in the trade tool's `codes`, and pull flows for the regions in "
                   "`revenue_by_region`. 🔴 But GATE it: Comtrade is cross-border EXIM only (no domestic "
                   "consumption) — a DOMESTIC-demand business (revenue_by_region home-only) has NO trade "
                   "angle; say so, don't force one. Empty `related_assets`/`revenue_by_region` = no "
                   "idiosyncratic driver (normal) OR not-yet-mapped — don't fabricate."),
    }

@mcp.tool(title="Stock Prices", annotations=_RO)
def stock_prices(ticker: Annotated[str, _dt(_TICKER)],
                 to: Annotated[Optional[str], _d("As-of date `YYYY-MM-DD` — features computed as of that day (point-in-time). Omit → latest.")] = None,
                 from_: Annotated[Optional[str], _d("Lower bound of price history `YYYY-MM-DD`. Narrowing below ~1y nulls the long windows. Price history goes back DECADES (unlike news, 2026+).")] = None,
                 country: Annotated[Optional[str], _d(_TK_COUNTRY)] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """Price context for a tradable ticker (stock / ETF / index-ETF / forex / crypto / commodity), split &
    dividend-ADJUSTED — a DIGESTED read, NOT a raw bar series: windowed changes (1w/1mo/3mo/ytd/1y), 52-week
    range + `drawdown_from_52w_high_pct` (how far below the peak), realized vol + `realized_vol_percentile_1y`
    (is today's vol high vs its OWN year), trend vs SMA50/200, volume conviction (`up_down_volume_ratio_1mo`,
    rvol). `*_read` fields are ready plain-language labels — quote them, don't re-derive. Reach for this on
    "is it cheap/extended / how has it moved / why is it dropping" — the LEVEL that makes a news+options read
    actionable (or use `asset_pulse` to get price + news + options in one). `to` = as-of date (point-in-time,
    YYYY-MM-DD, features as of that day); `from_` bounds history (narrowing below ~1y nulls the long windows).
    For a SECTOR/theme (not one ticker) use `theme_pulse`, not this. 🔵 BONDS/RATES: if `metric_kind` ==
    "yield" (a `.GB` govt-bond yield like US-10Y.GB or a `.MM` rate like SOFR.MM) the stored value is a
    LEVEL, not a price — narrate each window's `change_bps` in BASIS POINTS, NOT `change_pct` (a % of a
    yield is sign-inverted + the wrong unit; e.g. US-10Y 1y = "+52 bps", not "+12%"). Bonds also carry
    per-window `price_proxy_pct` + top-level `mod_duration` = an L1 bond-PRICE estimate (≈ −ModDur×Δy) for
    "the bond fell ~4%" narration (label it an ESTIMATE; for an exact bond return point to a bond ETF like
    TLT/IEF). Volume fields (`rvol`, `up_down_volume_ratio_1mo`, …) are `null` for a yield — don't present
    volume conviction; and yield↑ ⇒ bond price↓."""
    tk, cf, _det = _ticker_arg(ticker, scope=_SCOPE_PRICED, country=country, context=context)  # 🆕 collapse find_stock (priced instrument)
    if cf: return cf
    return mdx()._get(f"/v1/stocks/{tk}/prices", {"to": to, "from": from_}).data

@mcp.tool(title="Batch Stock Prices", annotations=_RO)
def stock_prices_batch(tickers: Annotated[List[str], _d("UP TO 50 MarketDX tickers (a watchlist/cohort). Returns `results` in input order + `unresolved`.")],
                       to: Annotated[Optional[str], _d("As-of date `YYYY-MM-DD` (point-in-time). Omit → latest.")] = None,
                       from_: Annotated[Optional[str], _d("Lower bound of price history `YYYY-MM-DD` (below ~1y nulls the long windows).")] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """The same digested price context for UP TO 50 tickers in ONE call — a watchlist / cohort snapshot
    ("which of these names are most extended, or deepest in drawdown"). Returns `results` (in input order)
    + `unresolved` (unknown / no-price-history tickers). `to`/`from_` as in `stock_prices`."""
    tks, cf, _det = _tickers_arg(tickers, scope=_SCOPE_PRICED, context=context)  # 🆕 collapse find_stock (batch; ONE reconfirm for ambiguous)
    if cf: return cf
    return mdx()._get("/v1/stocks/prices", {"tickers": ",".join(tks), "to": to, "from": from_}).data

def _options_brief(o: Optional[dict]) -> dict:
    """Compact an options-sentiment payload for a bundle: keep positioning_score + flow + per-horizon
    metrics (IV/gex/pcr/skew/max_pain, ~0.7KB) + read/because + slim key_dates; DROP only the big
    `per_bucket` audit block (~4.6KB → get it from `options_sentiment`) + the redundant top-level `_guide`
    (the composite carries its own), so it stays context-light even across N holdings."""
    if not o or o.get("covered") is False:
        return {"covered": False, "note": (o or {}).get("note")}
    s = o.get("sentiment") or {}
    hz = {k: {"positioning_score": v.get("positioning_score"),
              "metrics": v.get("metrics"),   # the raw numbers (IV/gex/pcr/skew/max_pain) — only ~0.7KB
              "signals": [{"read": g.get("read"), "because": g.get("because")}
                          for g in (v.get("signals") or [])]}
          for k, v in (s.get("horizons") or {}).items()}
    return {"positioning_score": s.get("positioning_score"), "stale": o.get("stale"),
            # audience = the style=plain narration mandate ("explain for a non-expert, no jargon"). KEEP it
            # — dropping it (with the rest of _guide) is what made the LLM narrate options technically.
            "audience": (s.get("_guide") or {}).get("audience"),
            "flow": s.get("flow"), "horizons": hz,
            "key_dates": [{"expiry": d.get("expiry"), "dte": d.get("dte"), "read": d.get("read"),
                           "because": d.get("because")} for d in (s.get("key_dates") or [])]}

@mcp.tool(title="Portfolio Pulse", annotations=_RO)
def portfolio_pulse(portfolio_id: Annotated[int, _d(_PID)],
                    top_n: Annotated[int, _d("How many top holdings (by value) to analyze with market lenses (default 3, cap 5).")] = 3,
                    window: Annotated[Optional[str], _d(_WINDOW)] = None) -> dict:
    """⭐ THE tool for "how is my portfolio doing?" / "how is my <holding> doing?" — the owner-scoped
    portfolio snapshot FUSED with the market lenses on its biggest positions, in ONE call. Returns
    `context` (holdings / performance / attribution / composition / flags — == portfolio_context) PLUS
    `holdings_pulse`: for the TOP-`top_n` positions by value, a COMPACT news→impact + options-positioning
    read, so you can explain WHAT is happening to the book, not just its numbers. Prefer this over
    `portfolio_context` alone whenever the user asks how the portfolio (or a position in it) is DOING;
    use `portfolio_context` for pure numbers/analytics (a period's sharpe, attribution, composition).
    Drill into any single holding with `asset_pulse(symbol)` for full detail. `top_n` default 3 (cap 5 —
    each holding adds credits + latency). `window` scopes the news recency. `portfolio_id` from
    `list_portfolios`; 404 if not the user's. Analyze as an analyst (marketdx://policy PORTFOLIO)."""
    cli = mdx()  # bind the caller's client in THIS thread (contextvar not set inside workers)
    frm = _win(window)
    ctx = cli.portfolio_context(portfolio_id)  # owner-scoped; surfaces 404 if not the user's
    nav = (ctx.get("summary") or {}).get("nav") or 0
    positions = [p for p in (ctx.get("positions") or []) if p.get("symbol")]
    top = sorted(positions, key=lambda p: abs(p.get("value") or 0), reverse=True)[:max(1, min(top_n, 5))]
    def _holding(p):
        sym = p["symbol"]
        try:
            imp = _slim_articles(_ser(cli.stock(sym).news(collapse=True, from_=frm, limit=3).to_list()), 3)
        except Exception as e:
            imp = {"error": str(e)}
        try:
            opt = _options_brief(cli._get(f"/v1/options/{sym}/sentiment", {"style": "plain"}).data)
        except NotFoundError:
            opt = {"covered": False}
        except Exception as e:
            opt = {"covered": False, "note": str(e)}
        w = round((p.get("value") or 0) / nav * 100, 1) if nav else None
        return {"symbol": sym, "name": p.get("name"), "weight_pct": w, "side": p.get("side"),
                "impact": imp, "options": opt}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(5, len(top) or 1)) as ex:
        holdings_pulse = list(ex.map(_holding, top))
    return {
        "context": _slim_context(ctx), "top_n": len(top), "holdings_pulse": holdings_pulse,
        "_guide": ("Analyze as a research analyst (marketdx://policy PORTFOLIO): LEAD with context.flags / "
                   "the dominant concentration / drawdown; explain the return from context…attribution; "
                   "THEN use holdings_pulse to say WHAT news + options positioning is driving the biggest "
                   "positions (tie each to its weight_pct). Narrate options from read/because; "
                   "covered=false → skip options for that name. Facts, not advice — hand the call back."),
    }

@mcp.tool(title="Theme Pulse", annotations=_RO)
def theme_pulse(q: Annotated[str, _dq("The SECTOR / INDUSTRY / THEME name ONLY — 'semiconductors', 'banks', 'energy', "
                                          "'AI', 'clean energy', 'gold' — or SEVERAL comma-separated ('semiconductors,cloud') "
                                          "to read together in one call. ⛔ Do NOT put a COUNTRY or REGION in `q`: the "
                                          "nationality ALWAYS goes in the `country` param, never here. 'European banks' → "
                                          "q='banks' + country='GB,DE,FR,IT,ES,NL,CH,SE'; 'Thai retail' → q='retail' + "
                                          "country='TH'; 'Japanese real estate' → q='real estate' + country='JP'. "
                                          "NOT a single company/ticker (→ asset_pulse), NOT a bond/rate (→ bond_pulse).")],
                country: Annotated[Optional[str], _d("Country/region scope — CSV of ISO-2 codes. 🌍 If the question names a "
                                          "nationality or region ('European', 'Thai', 'Chinese', 'ASEAN'), put it HERE (never in "
                                          "`q`); enumerate a region into its ISO-2s YOURSELF (Europe→'GB,DE,FR,IT,ES,NL,CH,SE'; "
                                          "ASEAN→'TH,SG,MY,ID,PH,VN'; 'China+US'→'CN,US'). Scopes the theme+gics news angles to "
                                          "companies LISTED there; the ETF-options + commodity angles stay GLOBAL.")] = None,
                window: Annotated[str, _d(_WINDOW)] = "30d") -> dict:
    """⭐ THE tool for "how is <a SECTOR / INDUSTRY / THEME> doing?" (semiconductors, tech, energy, banks,
    AI, clean energy, …) — a concept that spans MULTIPLE INDEPENDENT taxonomies. It resolves the concept
    and fans out, in ONE call, to EVERY angle that applies (skipping ones that don't), each a SEPARATE
    lens over a DIFFERENT dataset — present them separately, do NOT merge:
      • `theme` — the MarketDX MEGATREND cohort (our proprietary trend tree) → a brief (pulse / winners /
        losers / top stories). Membership = companies EXPOSED to the trend (can cross GICS sectors).
      • `gics` — the standard GICS SECTOR cohort → a brief. A DIFFERENT membership (strict sector
        classification) → genuinely different winners/losers than the megatrend.
      • `asset` — the tradable ETF's OPTIONS positioning (SMH/XLK/GLD/…) — fear-greed / dealer-gamma.
      • `commodity` — if the concept IS/HAS a tradable COMMODITY (gold, carbon, copper, oil), its digested
        PRICE read (level, windowed change, description, trend/vol). Fires even when there's NO options ETF
        (carbon/most metals) — that's the lens `asset` couldn't give. Narrate a `metric_kind:yield` in bps.
    Applicable angles VARY: 'semiconductors' → theme+gics+asset; 'carbon' → theme (Carbon-Removal cohort) +
    commodity (the EUA price); 'gold' → asset (GLD options) + commodity (GOLD.COMM price); 'AI' → theme (no
    single AI ETF). `skipped` lists the angles that didn't resolve.
    ⚠️ Use `asset_pulse(ticker)` for a SINGLE company/ETF; use `theme_pulse` for a sector/theme CONCEPT.
    🌍 A sector IN a country/region — "how are EUROPEAN banks / THAI retail / JAPANESE real-estate doing?" —
    just pass `country` (CSV of ISO-2; enumerate the region yourself). It scopes the news angles (theme+gics)
    to companies listed there; the ETF-options + commodity angles stay global. So 'European banks' =
    theme_pulse(q='banks', country='GB,DE,FR,IT,ES,NL,CH,SE') — ONE call, no need to pre-resolve the code.
    (For a single PRECISE cohort with no fan-out, `brief(gics=<sector code or name>, country=…)` is the alternative.)
    🧩 MULTIPLE sectors at once — "how are SEMICONDUCTORS and CLOUD in China doing?" — comma-separate them in
    `q` ('semiconductors,cloud'); theme+gics merge into one union pulse, asset+commodity list per concept. So
    "Chinese + American banks" = q='banks', country='CN,US'; "semis + cloud in China" = q='semiconductors,cloud', country='CN'.
    `window` = 7d/30d/90d/1y/…"""
    cli = mdx()
    from concurrent.futures import ThreadPoolExecutor
    # ── q may carry SEVERAL concepts (CSV) — resolve each independently, then aggregate the scope axes ──
    concepts = [c.strip() for c in q.split(",") if c.strip()] or [q]
    ctry = [c.strip().upper() for c in country.split(",") if c.strip()] if country else None

    def _resolve(concept):
        # concept → {megatrend?, gics?, etf?}. ONE unified Jev resolve decides both axes (theme + gics) from the
        # shared vector space — no gazetteer/keyword map (that mis-mapped "homebuilders"→Banks). The deepseek call
        # below is ETF-only (a tradable-fund pick, a separate concern from taxonomy resolution).
        _cr = _resolve_concept(concept)
        megatrend = next((int(x["id"]) for x in _cr.get("refs", []) if x["type"] == "theme"), None)
        gics = next((x["id"] for x in _cr.get("refs", []) if x["type"] == "gics"), None)
        etf = None
        try:
            r = _deepseek(
                "Pick the ONE best broad tradable ETF for a market concept from the provided covered list. "
                'Return JSON {"etf": <ticker from the list, or null if none fits>}. A country/region market IS '
                "a valid concept (China->MCHI, Hong Kong->EWH, Taiwan->EWT, Thailand->THD, Japan->EWJ). Prefer "
                "the PLAIN, unleveraged, broad fund; pick a LEVERAGED (2x/3x/bull/bear, e.g. YINN/SOXL/SPXL/"
                "TQQQ) or a narrow sub-slice (China A-Shares->ASHR, China internet/tech->KWEB, China large-cap->"
                "FXI) ONLY if the concept explicitly asks for leverage / A-shares / mainland / internet / "
                "large-cap. Bare 'China'/'Chinese stocks'/'China market' -> MCHI.",
                f"Concept: {concept}\nCovered ETFs: " + ", ".join(f"{k}={v}" for k, v in _COVERED_ETFS.items()),
                0.0)
            etf = r.get("etf") if r.get("etf") in _COVERED_ETFS else None
        except Exception:
            pass
        return {"concept": concept, "megatrend": megatrend, "gics": gics, "etf": etf}

    # Resolve concepts SEQUENTIALLY in THIS thread — _resolve → _resolve_concept does an mdx() search_concepts
    # API call, and a ThreadPoolExecutor worker does NOT inherit the request's auth contextvar (the
    # "no MarketDX API key" bug). The expensive angle fan-out below is still parallel (it reuses the already-
    # authed `cli`). Concept count is tiny (usually 1), so sequential costs nothing.
    resolved = [_resolve(c) for c in concepts]

    def _dedup(xs):
        out = []
        for x in xs:
            if x is not None and x not in out:
                out.append(x)
        return out
    # theme + gics angles MERGE across concepts (brief takes arrays → one union pulse); asset + commodity
    # stay PER-CONCEPT (each concept has its own ETF / commodity), returned as lists.
    megatrends = _dedup([r["megatrend"] for r in resolved])
    gics_codes = _dedup([r["gics"] for r in resolved])
    etf_concepts = [(r["concept"], r["etf"]) for r in resolved if r["etf"]]

    def _theme():
        if not megatrends:
            return None
        try:
            return {"megatrends": [_node_out(m) for m in megatrends],
                    "brief": _brief_slim(cli.brief(megatrend=megatrends, country=ctry, window=window))}
        except Exception as e:
            return {"error": str(e)}
    def _gics():
        if not gics_codes:
            return None
        try:
            return {"gics_codes": gics_codes, "brief": _brief_slim(cli.brief(gics=gics_codes, country=ctry, window=window))}
        except Exception as e:
            return {"error": str(e), "gics_codes": gics_codes}
    def _assets():  # per-concept ETF options positioning (global — an ETF has no listing country)
        out = []
        for concept, etf in etf_concepts:
            try:
                out.append({"concept": concept, "etf": etf, "etf_name": _COVERED_ETFS.get(etf),
                            "options": _options_brief(cli._get(f"/v1/options/{etf}/sentiment", {"style": "plain"}).data)})
            except NotFoundError:
                out.append({"concept": concept, "etf": etf, "covered": False})
            except Exception as e:
                out.append({"concept": concept, "etf": etf, "error": str(e)})
        return out or None
    def _commodities():  # per-concept COMMODITY price read (for a concept that IS/HAS a tradable commodity)
        out = []
        for concept in concepts:
            try:
                ms = cli._get("/v1/stocks", {"q": concept, "asset_class": "commodity", "limit": 5}).data.get("matches", [])
                cm = next((m for m in ms if m.get("type") == "commodity"), None)
                if not cm:
                    continue
                p = cli._get(f"/v1/stocks/{cm['ticker']}/prices", {}).data
                kw = {k: {x: v[x] for x in ("change_pct", "change_bps") if x in v}
                      for k, v in (p.get("windows") or {}).items() if k in ("1w", "1mo", "3mo", "1y", "ytd")}
                out.append({"concept": concept, "ticker": cm["ticker"], "name": cm.get("name"), "region": p.get("region"),
                            "currency": p.get("currency"), "description": p.get("description"),
                            "metric_kind": p.get("metric_kind"), "last_close": p.get("last_close"),
                            "range_read": p.get("range_read"), "trend_read": p.get("trend_read"),
                            "realized_vol_percentile_1y": p.get("realized_vol_percentile_1y"), "windows": kw})
            except Exception:
                continue
        return out or None

    with ThreadPoolExecutor(max_workers=4) as ex:
        ft, fg, fa, fc = ex.submit(_theme), ex.submit(_gics), ex.submit(_assets), ex.submit(_commodities)
        angles = {k: v for k, v in {"theme": ft.result(), "gics": fg.result(),
                                    "asset": fa.result(), "commodity": fc.result()}.items()
                  if v is not None}
    return {
        "query": q, "concepts": concepts, "window": window, "angles": angles,
        "skipped": [k for k in ("theme", "gics", "asset", "commodity") if k not in angles],
        "_guide": ("Present each angle SEPARATELY — they are DIFFERENT cohorts/lenses: `theme` = MarketDX "
                   "megatrend membership (trend-exposed, may cross sectors); `gics` = standard GICS sector "
                   "classification (different winners/losers); `asset` = a LIST of per-concept ETF options "
                   "positioning; `commodity` = a LIST of per-concept underlying COMMODITY PRICE reads "
                   "(level/change/trend — the price lens for carbon/gold/copper that has no options ETF; "
                   "narrate a `metric_kind:yield` move in bps). With MULTIPLE `concepts`, theme+gics MERGE "
                   "them into one union pulse while asset+commodity stay per-concept — so you can still tell "
                   "which concept each ETF/commodity belongs to. Do NOT merge the four angles. `skipped` "
                   "angles don't apply. Lead with the sharpest cross-angle read (megatrend vs GICS divergence, "
                   "options contradicting news breadth). Narrate options from its read/because for a non-expert."),
    }

@mcp.tool(title="Commodity Pulse", annotations=_RO)
def commodity_pulse(q: Annotated[str, _dq("A COMMODITY concept, in ENGLISH — translate first (ทองคำ/黄金→'gold', "
                                             "天然ガス/原油→'natural gas'/'crude oil', 铜→'copper'). Or pass a `SYMBOL.COMM` "
                                             "ticker to skip resolution. For a COMPANY use asset_pulse; a SECTOR → theme_pulse.")],
                    window: Annotated[Optional[str], _d(_WINDOW)] = None) -> dict:
    """⭐ "How is <a COMMODITY> doing?" — gold, oil, natural gas, copper, carbon, metals, agris, LME-vs-
    onshore-China variants. Resolves the NAME **within the commodity universe** (no company noise — a bare
    "natural gas" via the general resolver returns gas UTILITIES, not the commodity) and returns the digested
    PRICE + supply/demand & geopolitics NEWS + onshore/offshore VARIANTS. 🌐 Pass the ENGLISH concept
    (translate ทองคำ/黄金→"gold", 天然ガス/原油→"natural gas"/"crude oil" first). ⚠️ A COMMODITY has NO
    options / PE / competitors — don't expect them. For a COMPANY use `asset_pulse`; a SECTOR/theme →
    `theme_pulse`. `window` scopes the news recency (7d/30d/90d/…). You may also pass a `SYMBOL.COMM` ticker
    directly to skip resolution."""
    cli = mdx()
    frm = _win(window)
    # resolve WITHIN the commodity scope (asset_class=commodity → WHERE exchange_code='COMM')
    if q.upper().endswith(".COMM"):
        comms = [{"ticker": q.upper(), "name": None, "region": None, "currency": None}]
    else:
        ms = cli._get("/v1/stocks", {"q": q, "asset_class": "commodity", "limit": 6}).data.get("matches", [])
        comms = [m for m in ms if m.get("type") == "commodity"]
    if not comms:
        return {"error": f"no commodity matches '{q}'. Translate to the English concept (gold/crude oil/…); "
                         "for a COMPANY use asset_pulse, a SECTOR use theme_pulse."}
    t = comms[0]["ticker"]
    def _price():
        try:
            return cli._get(f"/v1/stocks/{t}/prices", {}).data
        except Exception as e:
            return {"note": f"price unavailable: {e}"}
    def _impact():
        try:
            params = {"collapse": "true", "limit": _lim(None, default=6)}
            if frm:
                params["from"] = frm
            return {"articles": _slim_articles(cli._get(f"/v1/stocks/{t}/news", params).data.get("results", []), 6)}
        except Exception as e:
            return {"error": str(e), "articles": []}
    def _pos():  # embed the futures-positioning summary (deterministic — so the model gets it without a 2nd call)
        try:
            d = cli._get("/v1/positioning", {"asset": t}).data
            if not d or d.get("__notfound"):
                return None
            return {"score": d.get("positioning_score"), "crowding": (d.get("crowding") or {}).get("state"),
                    "read": d.get("read")}
        except Exception:
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as ex:
        fp, fi, fpo = ex.submit(_price), ex.submit(_impact), ex.submit(_pos)
        p, impact, pos = fp.result(), fi.result(), fpo.result()
    kw = {k: {x: v[x] for x in ("change_pct", "change_bps") if x in v}
          for k, v in (p.get("windows") or {}).items() if k in ("1w", "1mo", "3mo", "1y", "ytd")}
    price = {"last_close": p.get("last_close"), "metric_kind": p.get("metric_kind"), "windows": kw,
             "range_read": p.get("range_read"), "trend_read": p.get("trend_read"),
             "drawdown_from_52w_high_pct": p.get("drawdown_from_52w_high_pct"),
             "realized_vol_percentile_1y": p.get("realized_vol_percentile_1y"),
             "volume_conviction_read": p.get("volume_conviction_read")}
    # variants = SAME-BASE siblings only (onshore/offshore, currency): NICKEL↔NICKEL_LME, CARBON_EU↔
    # CARBON_UK — the base is the symbol before the first '_'. Filters out unrelated commodities that the
    # scoped search merely ranked nearby (e.g. SODAASH sneaking into a "carbon" query).
    _base = (comms[0].get("symbol") or "").split("_")[0]
    variants = [{"ticker": m["ticker"], "name": m.get("name"), "region": m.get("region")}
                for m in comms[1:] if (m.get("symbol") or "").split("_")[0] == _base][:5]
    return {
        "ticker": t, "name": comms[0].get("name") or p.get("name"), "region": p.get("region"),
        "currency": p.get("currency"), "description": p.get("description"),
        "price": price, "impact": impact, "positioning": pos, "variants": variants,
        "_guide": ("Lead with the PRICE level + trend (quote the `*_read` labels). Explain the WHY from "
                   "`impact` — supply/demand, geopolitics, inventories. 🎯 The embedded `positioning` block is "
                   "the FUTURES crowd's stance (crowded = a contrarian RISK; whether the good news is already "
                   "priced-in) — weave its plain `read` into the answer; for the full breakdown call the "
                   "`positioning` tool. If `variants` exist (onshore vs "
                   "offshore, e.g. LME vs Shanghai; USD vs CNY/MYR), COMPARE them — an onshore-offshore "
                   "divergence is the insight (different currency → convert before comparing levels). A "
                   "commodity has NO options / PE / competitors — do not mention or flag them as missing. "
                   "`impact` empty = no news in coverage (2026-01-01+), say so plainly; price still stands. "
                   "🌐 TRADE LENS: a commodity IS a traded good → for the PHYSICAL supply/demand behind the "
                   "price you MAY deepen with the trade tools: `top_traders`(codes=this commodity) (who "
                   "produces/exports the most, or whose exports are growing/streaking), `top_partners` / "
                   "`search_trade` on the swing buyer (China imports rising/falling), `trade_balance`. Adds "
                   "the flow substrate news+price can't (e.g. 'global import demand +X%, China −2 quarters, "
                   "Chile exports +5y CAGR 14%'). BYOK — relay the connect CTA if no key."),
    }

# FX / rates / index concepts → the exact COT-mapped ticker (the /v1/stocks resolver is unreliable for these:
# "Japanese yen" → an ETF FXY.US, "Mexican peso" → the wrong cross-pair MXNAUD). Commodities resolve fine there.
_POS_ALIAS = {
    "euro": "EURUSD.FOREX", "eur": "EURUSD.FOREX", "japanese yen": "JPYUSD.FOREX", "yen": "JPYUSD.FOREX",
    "british pound": "GBPUSD.FOREX", "pound": "GBPUSD.FOREX", "sterling": "GBPUSD.FOREX",
    "swiss franc": "CHFUSD.FOREX", "franc": "CHFUSD.FOREX", "australian dollar": "AUDUSD.FOREX", "aussie": "AUDUSD.FOREX",
    "canadian dollar": "CADUSD.FOREX", "loonie": "CADUSD.FOREX", "mexican peso": "MXNUSD.FOREX", "peso": "MXNUSD.FOREX",
    "brazilian real": "BRLUSD.FOREX", "real": "BRLUSD.FOREX",
    "us 2y": "US-2Y.GB", "us 5y": "US-5Y.GB", "us 10y": "US-10Y.GB", "us 30y": "US-30Y.GB",
    "2 year treasury": "US-2Y.GB", "10 year treasury": "US-10Y.GB", "30 year treasury": "US-30Y.GB",
    "us 10 year treasury": "US-10Y.GB", "treasuries": "US-10Y.GB", "sofr": "SOFR.MM", "fed funds": "EFFR.MM", "effr": "EFFR.MM",
    "s&p 500": "SPY.US", "s&p": "SPY.US", "sp500": "SPY.US", "spx": "SPY.US", "nasdaq": "QQQ.US", "nasdaq 100": "QQQ.US",
    "dow": "DIA.US", "dow jones": "DIA.US", "russell": "IWM.US", "russell 2000": "IWM.US",
}

@mcp.tool(title="Futures Positioning (COT)", annotations=_RO)
def positioning(asset: Annotated[str, _dq(
        "A COMMODITY / FX / RATES / INDEX to read FUTURES positioning for — a concept IN ENGLISH (oil, gold, "
        "copper, natural gas, US 10Y treasury, euro, S&P 500; translate first) or a MarketDX ticker "
        "(WTI.COMM, US-10Y.GB, EURUSD.FOREX, SPY.US). NOT a single stock — a stock's positioning lives in "
        "OPTIONS, use options_sentiment.")]) -> dict:
    """⭐ How the FUTURES market is POSITIONED — the CFTC Commitment of Traders lens for commodities, FX,
    rates and equity indices (the non-equity TWIN of options_sentiment; the two together cover positioning
    for every asset class). Answers 'is this trade crowded?', 'is the smart money leaning the other way?',
    'is the good news already priced into positioning?'. Returns: `crowding` (the speculative crowd at a
    3-year extreme = a contrarian RISK, NOT a timing call), `smart_vs_crowd` (are commercial hedgers — who
    know the physical/fundamental side — leaning against the crowd), `momentum` (building or unwinding; a
    flip = regime change), `fragility` (a few big traders holding it = reverses fast), and ⭐
    `news_vs_positioning` (does recent news CONFIRM the crowd → priced-in, or CONTRADICT a crowded position →
    unwind risk). Weekly, as of the prior TUESDAY. For a RATE/YIELD asset (`.GB`/`.MM`) a long futures =
    positioned for LOWER yields (the reads already say it that way). 🗣 Every feature carries a PLAIN `read`
    — narrate it in EVERYDAY language for a beginner (no 'net'/'percentile'/'basis' jargon); say what it
    MEANS for risk. Facts, not advice — the verdict is yours. A stock / uncovered asset → `__notfound`: say
    futures positioning doesn't apply and use options_sentiment / the news read instead."""
    cli = mdx()
    a = asset.strip()
    ticker = _POS_ALIAS.get(a.lower()) or (a if "." in a else None)
    if ticker is None:  # commodity concept → resolve, preferring a COT-covered class (USD-FX / .COMM / .GB / .MM)
        ms = cli._get("/v1/stocks", {"q": a, "limit": 8}).data.get("matches") or []
        ms.sort(key=lambda m: (0 if (m.get("ticker") or "").endswith("USD.FOREX")
                               else 1 if (m.get("ticker") or "").endswith((".COMM", ".GB", ".MM"))
                               else 2 if (m.get("ticker") or "").endswith(".FOREX") else 3))
        ticker = (ms[0].get("ticker") if ms else a) or a
    return cli._get("/v1/positioning", {"asset": ticker}).data

@mcp.tool(title="CFTC / COT Futures Extremes", annotations=_RO)
def cot_extremes(
    asset_class: Annotated[Optional[Literal["commodity","fx","rates","equity_index"]], _d("Filter: `commodity` | `fx` | `rates` | `equity_index`. Omit = all.")] = None,
    limit: Annotated[Optional[int], _d("Max markets (default 15, max 50).")] = None,
) -> dict:
    """⭐ FUTURES / CFTC-COT speculative positioning extremes — which commodity / FX / rate / equity-INDEX
    FUTURES have the CROWD at a 3-year extreme right now (NOT single-stock equity options → for 'stretched
    put/call' or crowded STOCK names use options_scan). The discovery scan across every tracked
    futures market at once. COT / FUTURES lens ONLY. Surfaces stretched positioning (≥90th or ≤10th
    percentile of its own 3y history) that could unwind hard on a shock — a contrarian-RISK map, NOT buy/sell
    calls (an extreme can persist). Use for 'where is FUTURES positioning most crowded / stretched right now?'.
    🔴 WRONG TOOL for single-STOCK options crowding — 'stretched put/call', 'one-sided / crowded equity names',
    'most extreme options positioning across stocks': for those use options_scan (pattern='crowded / one-sided' —
    the equity-options opana lens across ~557 US optionable names). Narrate each `read` plainly."""
    p = {}
    if asset_class:
        p["asset_class"] = asset_class
    if limit:
        p["limit"] = limit
    return mdx()._get("/v1/positioning/extremes", p).data

@mcp.tool(title="Financials", annotations=_RO)
def financials(tickers: Annotated[Union[str, List[str]], _dts("1–8 comma-separated COMMON-STOCK companies to read/compare "
                                          "financial statements for. EACH entry can be EITHER an exact MarketDX ticker "
                                          "('AAPL.US', '2330.TW') — used directly — OR a bare symbol / company name "
                                          "('AAPL', 'Apple', 'トヨタ') which the SERVER resolves for you (no separate lookup "
                                          "step). 🔴 If an entry is AMBIGUOUS (same name/symbol across markets or entities) or "
                                          "is NOT a company, the tool returns `needs_confirmation` — follow its `_guide`. NOT for "
                                          "ETF/commodity/bond/crypto — no company financials.")],
               period: Annotated[Optional[str], _d(
                   "OPTIONAL time selector, mapped to each company's FISCAL year. Forms: '5' or '5y' = last 5 years "
                   "(default 5) · '2022' = that fiscal year · '2022-2023' = a range · '2020,2022' = specific years · "
                   "'5q' = last 5 quarters · '2024Q2' = one quarter · 'quarterly' = latest quarters. History reaches "
                   "~4–5 years back — an older specific year may be unavailable (the server says so).")] = None,
               fields: Annotated[Optional[Union[str, List[str]]], _d(
                   "OPTIONAL — the granularity dial. LEAVE EMPTY for the DIGEST (headline + ratios ROE/ROA/margins/debt/"
                   "current/quick + capital-return dividends/buybacks + abnormality signals) — the safe default that already "
                   "answers most reads/compares. Set it ONLY for a specific LINE ITEM the digest lacks. Comma-separated / a "
                   "list. 🆕 EACH entry can be EITHER an exact key OR a plain-English description — the SERVER resolves it for "
                   "you (no need to know the exact key, no separate resolver call):\n"
                   "  • exact key if you know it → used directly (fast): revenue, cost_of_revenue, gross_profit, "
                   "operating_income, ebit, ebitda, net_income, total_assets, current_assets, cash, inventory, receivables, "
                   "net_ppe, goodwill, intangibles, total_liabilities, current_debt, long_term_debt, total_debt, total_equity, "
                   "retained_earnings, operating_cash_flow, free_cash_flow, capex, dividends_paid, buybacks, … (BANK/INSURANCE "
                   "lines too). \n"
                   "  • don't know the key? just DESCRIBE the line — 🔴 in ENGLISH (translate first: ค่าความนิยม→'goodwill', "
                   "投資不動産→'investment properties') — e.g. 'construction in progress', 'held-to-maturity securities', "
                   "'accrued interest receivable'. Loose/approximate English is fine (the server matches meaning). \n"
                   "  • 'income' | 'balance' | 'cashflow' → that WHOLE statement · 'all' → every reported line (large).\n"
                   "🔴 If a term is AMBIGUOUS or NOT a financial-statement line, the tool returns `needs_confirmation` — "
                   "follow its `_guide`/`note` (pick from candidates and re-call, or tell the user it's unavailable). "
                   "Unreported-but-valid line → empty/`unavailable_fields`; state absences plainly, never fabricate. NOTE: "
                   "ratios/multiples (ROE, P/E) live in the DIGEST, not here.")] = None,
               currency: Annotated[Optional[str], _d("Convert ABSOLUTE totals to this currency (e.g. USD) at each "
                                                     "period's date so cross-currency companies compare — margins/growth "
                                                     "are currency-neutral anyway. A multi-company compare defaults to USD.")] = None,
               context: Annotated[Optional[str], _d(_TK_CONTEXT)] = None,
               ) -> dict:
    """⭐ Company FINANCIAL STATEMENTS — income / balance / cash-flow + auto-detected abnormality SIGNALS.
    Read ONE company or COMPARE up to 8 (revenue, growth, margins, ROE, FCF…).
    🔴 To compare/analyse SEVERAL companies, pass them ALL in ONE call (`tickers='TSLA.US,MSFT.US'`) — do NOT call once
    per company; a single call aligns them on a common basis + currency and costs a fraction of N separate calls. Pick
    ONE `period` per question too (quarterly figures ALREADY carry YoY vs the same quarter — no extra annual call needed).
    Data is a clean, current, normalized
    feed uniform across EVERY industry (banks, autos-with-captive-finance, insurance, REITs). 🎚 ONE dial = `fields`:
    leave it EMPTY for the DIGEST (the safe, small default — headline + ratios + capital-return + signals; covers
    most compares); set it only for specific line items, a whole statement ('income'|'balance'|'cashflow'), or 'all'.
    ⏱ `period` picks the time window (5y / 2022 / 2022-2023 / 5q / 2024Q2), mapped to each company's fiscal year.
    🌐 Cross-currency compares handled — `currency=USD` (auto for multi-company); totals convert at each period's DATE.
    🗣 The digest carries a plain `read` — narrate margins/growth/FCF/ROE in everyday words. Facts, not advice.
    🚩 The digest may carry `_notes` — deterministic per-period flags that a year's per-share/YoY figures aren't
    comparable (share splits & share-class/Up-C re-bases, goodwill/asset impairments or divestitures, debt carve-outs,
    one-period source misparses). The movement and its comparability WARNING are FACTS; each note's `likely_causes` is
    an INFERRED guess at WHY — treat it as a lead to VERIFY, not a stated fact (research it before asserting a cause).
    📏 LIMITS (relay them if the user asks beyond): ≤8 companies/call · ≤20 specific fields/call · ~4–5 years history.
    A non-equity (ETF/commodity/bond/crypto) or unlisted name → that entry is `ok:false` (say financials don't apply).
    🔴 `asset_pulse` on a stock ALREADY embeds the digest — call `financials` only for a DEDICATED read/compare, a
    specific-`fields`/statement pull, or `all`, NOT as a second call right after asset_pulse.
    💡 Prefer the digest first: unless the data would be too big (many companies × many years) or you need a line the
    digest lacks, the empty-`fields` digest is safer and often gives extra useful context for free."""
    # accept both a comma-string and a JSON array for tickers/fields (LLMs reach for either) → normalize to string.
    if isinstance(tickers, list): tickers = ",".join(str(t) for t in tickers)
    if isinstance(fields, list): fields = ",".join(str(f) for f in fields)
    # 🆕 TWO resolvers, ONE pattern (vector shortlist → Jev → gate; resolver-replacement-design §12/§13):
    #   • TICKERS (identity): full ticker w/ suffix → passthrough · bare symbol / company name → _resolve_ticker
    #   • FIELDS  (concept):  special token / exact key → passthrough · else → _resolve_fsconcept (SCOPE=field)
    # Anything ambiguous / out-of-domain → ONE BATCHED reconfirm (return without querying). identity ≠ head:
    # _resolve_ticker returns the ticker the user MEANT; /v1/financials maps it to the canonical head itself.
    _SPECIAL = {"income", "balance", "cashflow", "all"}
    tk_list: list = []             # resolved/passthrough tickers to send to /v1/financials
    tk_detail: dict = {}           # per-ticker interpretation (soft-surface transparency)
    tk_pending: list = []          # tickers needing reconfirm/no_match
    tk_ok: list = []               # resolved tickers for the batched-reconfirm `resolved` block
    for raw in tickers.split(","):
        tok = raw.strip()
        if not tok:
            continue
        # passthrough ONLY a real full ticker `SYMBOL.EXCH` (BRK.B's ".B" is a share class → resolve, not a broken
        # passthrough). NOTE: financials keeps this INLINE walk (not the shared _tickers_arg) because its reconfirm is
        # COMBINED with the fields axis below — one envelope surfaces bad ticker(s) AND bad field(s) together.
        if _is_full_ticker(tok):
            tk_list.append(tok); continue
        r = _resolve_ticker(tok, scope=_SCOPE_STOCK, context=context)   # financials = common stocks only
        if r["status"] == "resolved":
            tk_list.append(r["ticker"]); tk_ok.append(r)
            tk_detail[tok] = {"ticker": r.get("ticker"), "confidence": r.get("confidence"), "gate": r.get("gate"),
                              **({"note": r["note"]} if r.get("note") else {})}
        else:
            tk_pending.append(r)
    field_list: list = []          # resolved/passthrough keys to send to /v1/financials
    resolved_detail: dict = {}     # per-entry interpretation (soft-surface transparency)
    pending: list = []             # entries needing reconfirm/no_match
    resolved_ok: list = []         # (query, key, conf, gate) for the batched-reconfirm `resolved` block
    for raw in (fields.split(",") if fields else []):
        tok = raw.strip()
        if not tok:
            continue
        if tok.lower() in _SPECIAL:
            field_list.append(tok.lower()); continue
        r = _resolve_fsconcept(tok, scope_types=("field",))  # financials serves LINE ITEMS only
        if r["status"] == "resolved":
            field_list.append(r["key"]); resolved_ok.append(r)
            resolved_detail[tok] = {"key": r.get("key"), "confidence": r.get("confidence"), "gate": r.get("gate"),
                                    **({"note": r["note"]} if r.get("note") else {})}
        else:
            pending.append(r)
    if tk_pending or pending:
        # BATCHED reconfirm — return the WHOLE set (tickers + fields) at once WITHOUT querying. Client resolves the
        # pending ones, then RE-CALLS with the chosen ticker(s)/key(s) (exact tickers + keys → passthrough, Jev not re-run).
        return {
            "needs_confirmation": True,
            "resolved": {
                **{r["query"]: {"ticker": r["ticker"], "confidence": r.get("confidence"), "gate": r.get("gate")} for r in tk_ok},
                **{r["query"]: {"key": r["key"], "confidence": r.get("confidence"), "gate": r.get("gate")} for r in resolved_ok},
            },
            "confirm": {
                **{r["query"]: {"kind": "ticker", "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])} for r in tk_pending},
                **{r["query"]: {"kind": "field", "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])} for r in pending},
            },
            "_guide": "Some inputs need attention. For each under `confirm`: `kind=ticker` → pick the right `ticker` from "
                      "its `candidates` (same company/symbol across markets or entities — decide from the user's intent/"
                      "context, else ASK which); `kind=field` + status=`reconfirm` → pick the right `concept` from its "
                      "`candidates`; status=`no_match` → that term isn't a company (ticker) or a financial-statement line "
                      "(field) — tell the user it's unavailable, don't force it. Then RE-CALL financials with the chosen "
                      "ticker(s) in `tickers=` and key(s) in `fields=` ALONGSIDE the already-`resolved` ones (they pass straight through).",
        }
    tks = tk_list
    params: dict = {"tickers": ",".join(dict.fromkeys(tks))}
    if period and period.strip():
        params["period"] = period.strip()
    if field_list:
        params["fields"] = ",".join(dict.fromkeys(field_list))  # dedup, keep order
    if currency:
        params["currency"] = currency.strip().upper()
    elif len(tks) > 1:
        params["currency"] = "USD"  # a compare → a common currency by default
    # text render — same data as JSON but a compact table (abbreviated numbers), ~70% fewer tokens; the LLM wants the
    # big picture, not exact digits. (asset_pulse's fundamentals embed keeps JSON — it extracts structured fields.)
    params["format"] = "text"
    data = mdx()._get("/v1/financials", params).data
    if isinstance(data, dict):  # show how each entry was interpreted (soft-surface transparency)
        if tk_detail: data["_resolved_tickers"] = tk_detail
        if resolved_detail: data["_resolved_fields"] = resolved_detail
    return data

class ScreenCondition(BaseModel):
    """ONE AND-ed screen condition. COMMON form = a metric + a shape + its value: put the METRIC in `concept` and
    the SHAPE in `pattern` — EACH may be an exact key OR plain natural language; the SERVER resolves it, so you
    send them straight here (no separate resolver step). Then set the ONE value the
    pattern needs. RELATION form (rare) = compare two metrics: set metricA + relation + metricB instead."""
    # extra='forbid': the TOOL owns the param set — an unknown/typo'd field is rejected HERE with a clear error
    # (naming the bad field), never silently dropped and run with a default. See mcp-tool-guidance-audit.
    model_config = ConfigDict(extra="forbid")
    concept: Optional[str] = Field(None, description="The METRIC — an exact key (pe, roe, net_margin, revenue, debt_to_equity, …) OR plain natural language ('return on equity', 'gross margin', 'accrued interest receivable'). The server resolves it. 🔴 ENGLISH.")
    pattern: Optional[str] = Field(None, description="The SHAPE — an exact key (above, below, between, low, high, accelerating, below_average, compound_growth, …) OR plain natural language ('grew every year', 'margin contracting', 'above the sector average'). The server resolves it. 🔴 ENGLISH.")
    threshold: Optional[float] = Field(None, description="The number for `above`/`below`. 🔴 `above`/`below` are ABSOLUTE-level screens and REQUIRE a threshold — there is NO server default (above 15? 20? is arbitrary), so a bare `above`/`below` with no number 400s. So: if the USER stated a number ('P/E above 15') → send it here. If the user gave only a VAGUE quality word ('quality', 'high ROE', 'cheap') with NO number → do NOT use `above`/`below`; use the COHORT pattern `above_average` / `below_average` instead (peer-relative, needs no number, has a real default = the cohort average). Only the cohort/percentile patterns (above_average, below_average, top_quartile, high, low…) may omit a number. Never invent a threshold. SCALE: a ratio/percent metric is a FRACTION — send 0.20 for 20% (roe, margins, growth, yields). (P/E, P/B, EV/EBITDA and coverage multiples are NOT fractions — send 15 for a P/E of 15.)")
    min: Optional[float] = Field(None, description="Lower bound for `between`.")
    max: Optional[float] = Field(None, description="Upper bound for `between`.")
    N: Optional[int] = Field(None, validation_alias=AliasChoices("N", "n"), description="Window in YEARS for growth/consecutive patterns — supply ONLY when the user stated the span ('over the last 3 years' → 3). Omit otherwise; the server uses the pattern's default window.")
    percentile: Optional[float] = Field(None, description="Tail fraction for `low`/`high` — supply ONLY when the user named a tail size ('cheapest 10%' → 0.1). Omit otherwise; `low`/`high` default to the 20% tail. For a vague degree ('very cheap') prefer a degree token over a number.")
    total_change: Optional[float] = Field(None, description="compound_growth / compound_decline ONLY — the CUMULATIVE change over the WHOLE N-year window, as a fraction: 1.0 = doubled (2×) or halved, 0.5 = +50% (grew) / −50% (fell). Use for 'grew/fell X TIMES over the period' — 'market cap doubled in 2 years' → {pattern:'compound_growth', N:2, total_change:1.0}. 🔴 NOT per-year — that's `cagr`. (Response returns BOTH change_total and cagr so you never guess.)")
    cagr: Optional[float] = Field(None, description="compound_growth / compound_decline ONLY — the ANNUALIZED rate PER YEAR, as a fraction: 0.20 = 20%/yr. Use for 'grew/fell X% per year' — 'revenue compounding 15%/yr over 5y' → {pattern:'compound_growth', N:5, cagr:0.15}. 🔴 NOT the whole-window total — that's `total_change`.")
    vs_cohort: Optional[dict] = Field(None, description="RARELY needed — usually OMIT. For a cohort pattern (below_average/above_average) the benchmark DEFAULTS to your screening scope (the `universe`): 'retail stocks with P/E below average' = scope `universe` to retail (the `gics` param, code-or-plain-English) and OMIT this — 'below average' then means below the RETAIL average automatically. Set this ONLY to benchmark against a DIFFERENT group than you're screening (e.g. US retail vs the GLOBAL retail average). Shape: {gics?: a GICS code PREFIX string like '45' — NOT a boolean/flag; country?: ISO-2; size?: ['large'|'mid'|'small'|'micro']; stat?: 'pooled'(default)|'median'}. 🔴 EACH STOCK vs ITS OWN SECTOR (whole-market, mixed sectors, in ONE screen — a bank judged vs banks, a tech vs tech): set {own: true} (or {own:'gics_group'} / {own:'gics_industry'} for a finer grain than the default sector). Use `own` ONLY for that cross-sector 'each vs its own' case; to compare WITHIN a single sector, scope the `universe` to that sector and omit vs_cohort instead.")
    metricA: Optional[str] = Field(None, description="RELATION form only: the first metric — an exact key OR plain English (a statement line, ratio, or valuation multiple); the server resolves it. To use its GROWTH RATE instead of its level, set metricA_stat='growth'.")
    relation: Optional[str] = Field(None, description="RELATION form only — how metricA relates to metricB. One of: 'higher_than' (metricA ≥ multiple×metricB, i.e. the RATIO A/B ≥ multiple), 'lower_than' (metricA ≤ multiple×metricB), 'ratio_between' (min ≤ A/B ≤ max — A is between min and max as a fraction of B), 'ratio_near' (A/B ≈ target within ±band), 'growth_faster_than' / 'growth_slower_than' (metricA's multi-year CAGR vs metricB's). Param per relation: higher/lower_than→`multiple`; ratio_between→`min`+`max`; ratio_near→`target`(+`band`, default ±10%); the growth ones take none. The bound `k` is just the number in `A vs k×B` — a FRACTION when you mean 'A is k% OF B' (0.15 = 15% of revenue), or a DIRECT ratio when the two operands are already comparable and you want A vs a multiple of B (k=1 for 'A ≤ B'; k=2 for 'A ≥ 2×B'). Operands are compared in their OWN units (e.g. a growth-rate operand is a PERCENT: 25 for 25%), so a plain-number metric vs a percent metric needs NO rescaling of k.")
    metricB: Optional[str] = Field(None, description="RELATION form only: the second metric — an exact key OR plain English (same vocabulary as metricA); the server resolves it. Set metricB_stat='growth' to compare against its GROWTH RATE instead of its level.")
    metricA_stat: Optional[str] = Field(None, description="RELATION form: how to read metricA — 'level' (default) or 'growth' (its N-year growth rate as a percent, e.g. 25 for 25%). Use 'growth' to build value-vs-growth ratios like PEG: {metricA:'pe', relation:'lower_than', metricB:'eps_diluted', metricB_stat:'growth', multiple:1} = P/E ÷ earnings-growth% ≤ 1. N (default 3) sets the window.")
    metricB_stat: Optional[str] = Field(None, description="RELATION form: how to read metricB — 'level' (default) or 'growth' (its N-year growth rate as a percent). See metricA_stat.")
    multiple: Optional[float] = Field(None, description="RELATION bound k for higher_than/lower_than — compares metricA to k×metricB (default 1 = plain metricA vs metricB). It is the raw number in 'A vs k×B', NOT always a fraction: use a FRACTION only when you mean 'A is k% OF B' ('R&D ≥ 15% of revenue' → metricA=rnd, higher_than, metricB=revenue, multiple=0.15; 'debt ≤ half of equity' → multiple=0.5); use a DIRECT ratio when the operands are already comparable ('cash ≥ 2× debt' → multiple=2; 'A ≤ B' → multiple=1). Each operand is in its OWN units (a growth-rate operand is a PERCENT, e.g. 25 for 25%), so do NOT rescale k to reconcile units. Ignored by growth_faster/slower_than.")
    target: Optional[float] = Field(None, description="RELATION `ratio_near` only: the ratio A/B to sit near, as a FRACTION (0.15 = ~15% of metricB). 'capex around 8% of revenue' → metricA=capex, ratio_near, metricB=revenue, target=0.08.")
    band: Optional[float] = Field(None, description="RELATION `ratio_near` only: half-width tolerance as a FRACTION of target (default 0.10 = accept target ±10%). Omit unless the user named a tightness.")
    params: Optional[dict] = Field(None, description="Fallback ONLY — prefer the top-level threshold/min/max/N/percentile/multiple above. If you nest the value here ({threshold:…}) it's still read.")


def _cond_to_api(c: ScreenCondition) -> dict:
    """Typed condition → the news-api's shape (metric/pattern + nested params). Keeps the client's schema flat."""
    if c.metricA and c.metricB and c.relation:
        out = {"metricA": c.metricA, "relation": c.relation, "metricB": c.metricB}
        # forward EVERY ratio-bound operand the relation executors read (top-level OR nested params) — without them the
        # news-api silently defaults and mis-screens. Each relation reads only its own: higher/lower_than→`multiple`;
        # ratio_between→`min`+`max`; ratio_near→`target`(+`band`); growth_faster/slower_than→`N`. Server accepts flat,
        # so pass flat. Names are IDENTICAL across catalog/field/relay/executor (no rename → no "unknown param" drift).
        np = c.params or {}
        for k in ("multiple", "min", "max", "target", "band", "N", "metricA_stat", "metricB_stat"):
            v = getattr(c, k, None)
            if v is None: v = np.get(k)
            if v is not None: out[k] = v
        return out
    # read each value from the top-level field OR a nested params{} — find_fspattern's output says "params: threshold",
    # so an LLM often nests the value there instead of at the condition top-level; accept either so it never needs a retry.
    np = c.params or {}
    pick = lambda name, *alts: next((v for v in ([getattr(c, name)] + [np.get(k) for k in (name, *alts)]) if v is not None), None)
    threshold, mn, mx, n, pct = pick("threshold"), pick("min"), pick("max"), pick("N", "n"), pick("percentile")
    tc, cg = pick("total_change"), pick("cagr")
    p: dict = {}
    if threshold is not None: p["threshold"] = threshold
    if mn is not None: p["min"] = mn
    if mx is not None: p["max"] = mx
    if n is not None: p["N"] = n
    if tc is not None: p["total_change"] = tc
    if cg is not None: p["cagr"] = cg
    # canonical: pass `percentile` through UNCHANGED — the fund executor interprets it per pattern (low = bottom tail,
    # high = top tail). Do NOT rename to min/max_percentile here — the catalog + executor now declare `percentile`, and
    # the old rename made a hinted `percentile` call 400 ("unknown param 'max_percentile'"). One name, all layers.
    if pct is not None: p["percentile"] = pct
    d: dict = {"concept": c.concept, "pattern": c.pattern, "params": p}
    if c.vs_cohort: d["vs_cohort"] = c.vs_cohort
    return d


# ── TECHNICAL leg of screen_unified: the step/signal grammar ────────────────────────────────────────────
# The `pattern` (SHAPE, signals axis) and operands `a`/`b` (LINES, indicators axis) are resolved SERVER-SIDE
# inside screen_unified (_resolve_tasignal / _resolve_ta_indicator → /v1/ta/find-signal). There is NO separate
# find_tasignal tool — the client sends key-or-plain-English straight into a TaSignal. Field descriptions below
# ported from docs/pipeline/ta-screener-mcp-guide.md (blind-client-validated).

class TaSignal(BaseModel):
    """ONE technical signal = a SHAPE (`pattern`) + its operand LINES (`a`/`b`). Each is a key/token OR plain
    English — the SERVER resolves each."""
    model_config = ConfigDict(extra="forbid")  # unknown/typo'd field → rejected here, not silently dropped
    pattern: str = Field(..., description="The chart SHAPE — an exact pattern key OR plain English ('golden cross', 'breaking out of a squeeze', 'rolling over'); the server resolves it. 🔴 ENGLISH. Volatility-squeeze family (all OPERAND-FREE) — 🔴 you almost never need to CHAIN these; there are exactly TWO clean single-anchor intents: (1) 'which stocks are COILING / very quiet NOW' → `bb_squeeze` with a SHORT `window_bars` (e.g. 3); each hit carries a strength 0..1 where ~1.0 = the tightest coil. (2) 'coiled THEN broke out UP/DOWN' → `squeeze_fired_up` / `squeeze_fired_dn` — these are SELF-CONTAINED (a squeeze necessarily precedes its fire), so use ONE as the anchor; do NOT build a two-step `squeeze THEN fire` chain (it needs the coil and the release to hold at the same bar and returns 0). `ttm_squeeze` / `volatility_squeeze` = the narrow Bollinger-INSIDE-Keltner (TTM/Carter) variant — use only when the user names TTM/Keltner. `squeeze_started` is advanced (a bare coil-start bar) — prefer bb_squeeze / squeeze_fired_up above. More operand-free shortcuts: `kumo_squeeze` / `kumo_expand` (ichimoku cloud thinning/thickening) and `near_ma` (price pulled back to a moving average — defaults to the 200-day; pass b='ema50'/'sma200' for another). The generic `squeeze`/`converge`/`expand` REQUIRE operands a+b and cover the same plus a MA pair (ema50/ema200…), macd, BOLLINGER BANDS (a='bb_upper', b='bb_lower'), ICHIMOKU tenkan/kijun, and PRICE-vs-MA (a='close', b='ema200') — prefer the operand-free shortcuts above when they fit. 52-week range: `at_new_high` / `near_high` / `at_new_low` / `near_low` (operand-free; near_* takes optional b=tolerance fraction) and `off_high_by` (drawdown from the 52w peak, b=fraction e.g. 0.30 — peak→now, NOT net_change's start→now). Volume: `volume_spike` (one-bar surge) and `rising_volume` (climbing N bars, set for_bars). Oscillator BAND: for 'RSI between 40 and 50' (or any oscillator inside a numeric band) use the SINGLE pattern `in_range` with a='rsi' and b='40-50' — ONE condition, do NOT AND two above/below steps (a=oscillator, b='lo-hi'; optional for_bars = held N bars in the band). Full set: crossover_up, crossover_down, touch_up, touch_down, above, below, overbought, oversold, in_range, rising, falling, ttm_squeeze, bb_squeeze, squeeze_started, squeeze_fired, squeeze, converge, expand, divergence_bull, divergence_bear, volume_spike, rising_volume, volume_dryup, net_change_up, net_change_down, at_new_high, near_high, at_new_low, near_low, off_high_by.")
    a: Optional[str] = Field(None, description="Operand A (the SUBJECT line) — an exact token (close/ema50/rsi/macd_line) OR plain English ('the 50-day average', 'trend strength', 'the fast stochastic'); the server resolves either. For a cross/touch: the ACTIVE line that moves (two MAs → the FASTER/shorter; price-vs-MA → 'close'). For an above/below STATE: read it literally as 'a is above/below b' — 'price above the 200-day' → a='close', b='ema200'; 'the 50-day above the 200-day' → a='ema50', b='ema200'. Oscillator-vs-level → the oscillator (rsi, stoch_k, macd_line). Pass the EXACT indicator+period the user asked even if non-standard (ema45, sma150, rsi7) — the server snaps to the nearest supported line and returns a note; do NOT pre-round. Omit for operand-free patterns (volume_spike, rising_volume, divergence_bull/bear, overbought, oversold, ttm/squeeze transitions, the 52-week range patterns). Tokens: close, ema<n>, sma<n>, rsi, macd_line, macd_signal, stoch_k, adx, bb_upper, bb_lower, senkou_a, senkou_b, tenkan, kijun. If unsure which line a phrase means (e.g. 'volatility' → atr, 'trend strength' → adx, 'the 30-day average' → ema30, 'the cloud' → senkou_a/senkou_b), just send the plain-English phrase — the server resolves it; do not guess a token.")
    b: Optional[str] = Field(None, description="Operand B — the PASSIVE reference line (a token/English, server-resolved) OR a numeric level being crossed/referenced. Two moving averages → the SLOWER (longer). Oscillator-vs-level → the level as a string ('0','30','70'). MACD-vs-signal → 'macd_signal'. 🔴 For a NET-RETURN pattern (net_change_up/net_change_down / price_up_over / price_down_over), `b` = the move MAGNITUDE as a FRACTION: 30% → '0.30' (NOT '30'). Omit if the pattern has no reference.")
    for_bars: Optional[int] = Field(None, description="Require a state/level to have HELD for at least this many CONSECUTIVE bars of the timeframe (e.g. 'above the 200-day for a month' on a daily chart ≈ 20 bars). ⚠️ For rising/falling this is a RUN-LENGTH, not a lookback window. NOT valid on net_change / crossover / divergence (the server ERRORS) — for 'within the last N bars' use `window_bars`, not for_bars.")
    window_bars: Optional[int] = Field(None, description="PER-SIGNAL lookback window in BARS of the timeframe — 'this condition holds WITHIN the last N bars' (recency); for a net-return pattern it is the PERIOD the return is measured over ('dropped 30% over 100 days' → window_bars=100). USE THIS to give conditions DIFFERENT windows in one screen: 'RSI crossed 80 within 20 days AND price dropped 30% over 100 days' → {crossover_up, window_bars:20} + {net_change_down b:'0.30', window_bars:100}. Omit → the screen-level window_bars default. DISTINCT from for_bars (how long a state has HELD; recency vs duration).")
    timeframe: Optional[int] = Field(None, description="PER-CONDITION chart timeframe — 1=daily, 2=weekly, 3=monthly. Use to MIX timeframes in ONE screen (multi-timeframe): put it on a QUALIFIER so that condition is checked on its OWN chart while the anchor stays on the screen-level `timeframe`. e.g. 'weekly holds above the 50-week AND daily just crossed up' → screen timeframe=1 (daily), anchor={crossover_up, a:'ema50', b:'ema200'}, qualifier={above, a:'close', b:'ema50', timeframe:2}. Operand periods are BARS of THIS timeframe (a '50-week MA' on weekly = a 50-bar MA → ema50). Omit → the screen-level `timeframe`. ⚠️ On an ANCHOR it must equal the screen-level `timeframe` (the anchor defines the driver chart) — a mismatch 400s; put the cross-timeframe test in a qualifier.")


class TaQual(BaseModel):
    """An AND qualifier at a moment — a group of signals combined with OR (≥1 must hold)."""
    model_config = ConfigDict(extra="forbid")  # unknown/typo'd field → rejected here, not silently dropped
    any: List[TaSignal] = Field(..., description="Signals combined with OR; at least one must hold. Max 3.")
    within: Optional[int] = Field(None, description="± tolerance in trading bars around the anchor (default 5; use 0 for a persistent state like 'is above').")


class TaStep(BaseModel):
    """ONE moment. Multiple steps = a THEN chain (step 0 happens, THEN step 1 …). Same-moment conditions go in ONE step."""
    model_config = ConfigDict(extra="forbid")  # unknown/typo'd field → rejected here, not silently dropped
    anchor: List[TaSignal] = Field(..., description="Primary signal(s) for this moment; multiple = OR; also the sort key. Max 3.")
    quals: Optional[List[TaQual]] = Field(None, description="Extra conditions that must ALL hold at this moment (AND). Max 4.")


@mcp.tool(name="screen_unified", title="Unified Screener (Universe × Fundamental × Technical)", annotations=_RO)
def screen_unified(
        fundamental: Annotated[Optional[List[ScreenCondition]], _d(
            "The FUNDAMENTAL leg — AND-ed financial conditions (INTERSECT). Each condition = a METRIC (`concept`) + a "
            "SHAPE (`pattern`) + its value — send `concept`/`pattern` as an exact key OR plain English; the SERVER "
            "resolves each (no separate resolver step). e.g. roe>20% & 3y revenue "
            "growth → [{concept:'roe',pattern:'above',threshold:0.20},{concept:'revenue',pattern:'consecutive_growth',N:3}] "
            "(or NL: [{concept:'return on equity',pattern:'above 20%'...}] resolves the same). "
            "🔴 A fundamental TREND's TIME SPAN goes in THIS condition's `N` (in YEARS): 'PE declining over 2 years' → "
            "{concept:'pe',pattern:'consecutive_decline',N:2}. This is SEPARATE from the TA leg's window_bars. "
            "Omit for a TA-only screen.")] = None,
        ta: Annotated[Optional[List[TaStep]], _d(
            "The TECHNICAL leg — a THEN chain of steps (usually ONE step). Each signal's `pattern` (the SHAPE) and its "
            "operands `a`/`b` (the LINES) are each an exact key/token OR plain English — the SERVER resolves each (no "
            "separate resolver step). e.g. a golden cross with a volume spike → "
            "[{anchor:[{pattern:'crossover_up',a:'ema50',b:'ema200'}],quals:[{any:[{pattern:'volume_spike'}]}]}] "
            "(or NL: [{anchor:[{pattern:'golden cross',a:'the 50-day',b:'the 200-day'}],quals:[{any:[{pattern:'volume surge'}]}]}]). "
            "🔴 'within the last N bars' can be set PER SIGNAL via each signal's own `window_bars` (so conditions may have "
            "DIFFERENT windows — e.g. crossover within 20 + drop over 100); a signal without one falls back to the "
            "screen-level `window_bars`. 🔴 MULTI-TIMEFRAME: mix daily/weekly/monthly in ONE screen by setting a "
            "qualifier's own `timeframe` (1/2/3) — 'weekly holds above the 50-week AND daily just crossed up' → screen "
            "timeframe=1, anchor crossover_up, qualifier {above, a:'close', b:'ema50', timeframe:2}. Omit for a "
            "fundamentals-only screen.")] = None,
        options: Annotated[Optional[str], _d(
            "The OPTIONS leg — an options-behaviour term, an exact key OR plain English ('fear_building', 'iv_cheap', "
            "'the options crowd getting brave', 'cheap implied vol'); the server resolves it (no separate resolver "
            "step). Intersects the ~557 US-optionable names whose options market shows that behaviour with the other "
            "legs — 'biotech stocks the options crowd is getting brave on' → gics='352010' + options='the crowd "
            "getting brave'. 🔴 DIVERGENCE (options positioning FIGHTING the price trend) = send it here too ('options "
            "positioning diverging from the price uptrend') — the server expands it into the multi-leg screen itself. "
            "🔴 ENGLISH. US-optionable only. Omit for a non-options screen.")] = None,
        options_horizon: Annotated[Optional[Literal["long","short"]], _d("Options horizon: 'long' (default, positioning/conviction) or "
            "'short' (gamma/near-term). Only meaningful with `options`.")] = None,
        gics: Annotated[Optional[str], _d("OPTIONAL universe SCOPE — the industry/theme CONCEPT(s) to screen within. "
            "Pass one or MORE ATOMIC concepts, comma-separated (decompose a compound like 'banks and insurance' → "
            "'banks,insurance'). Each may be plain English ('banks', 'semiconductors', 'AI', 'EV cars', 'cloud') OR a "
            "raw GICS code prefix ('45'=IT sector, '3520'=biotech group, '352010'=biotech industry; shorter = broader). "
            "🔴 The SERVER resolves each concept and DECIDES the axis for you — an established industry maps to a GICS "
            "sector/industry, a curated megatrend maps to a THEME (you do NOT need to know our theme catalog or pick "
            "gics-vs-theme). A single concept may resolve to MULTIPLE homes (retail → discretionary + staples retail). "
            "If a concept isn't a recognizable industry/theme you get an honest reconfirm. 🔴 ENGLISH. Omit = all sectors.")] = None,
        country: Annotated[Optional[List[str]], _d("OPTIONAL operating-country scope — one or MORE ISO-2 codes, OR'd (a stock "
            "matches if in ANY of them). e.g. ['US'] · ['CN','US'] for China+US · ['TH','SG','MY']. Omit = all countries.")] = None,
        size: Annotated[Optional[List[str]], _d("OPTIONAL market-cap size tier(s), OR'd — any of 'large'|'mid'|'small'|'micro'. "
            "🔴 RELATIVE per-market MSCI cumulative-cap tiers (top 70% of a market's cap = 'large', 70-85% = 'mid', "
            "85-99% = 'small', tail = 'micro') — 'small' means small FOR ITS market, NOT small in USD (mega-caps are "
            "'large'; there is no separate 'mega'). For an ABSOLUTE USD size / 'under $X' use min/max_market_cap_usd, "
            "not this. e.g. ['large'] · ['mid','small']. Omit = all sizes.")] = None,
        asset_type: Annotated[Optional[List[str]], _d("OPTIONAL asset type(s), OR'd — from the asset_universe catalog: "
            "'Common Stock','ETF','Crypto','Currency','Commodity','Bond','Index','Fund','ADR','REIT'. e.g. ['Common Stock'] · ['ETF','Fund'] · ['Crypto']. "
            "NOTE: 'Crypto' = digital assets (BTC/ETH, exchange .CC) — SEPARATE from 'Currency' which is forex pairs (.FOREX); "
            "gold/silver spot are 'Commodity'. Omit = all types (a typical company screen wants 'Common Stock'). Scopes the TECHNICAL universe.")] = None,
        theme: Annotated[Optional[List[int]], _d("ADVANCED raw-passthrough — megatrend THEME node_id(s), OR'd; a stock matches "
            "if it is a CORE member of ANY. e.g. [18000000] · [18000000,18120000]. 🔴 Normally you do NOT set this: just name "
            "the theme concept in `gics` ('AI', 'semiconductors') and the server routes it to the theme axis automatically. "
            "Use this only when you already hold a numeric node_id and want to skip resolution.")] = None,
        exclude_gics: Annotated[Optional[str], _d("OPTIONAL — EXCLUDE industry/theme CONCEPT(s) from the whole screen "
            "(NOT banks / everything-except-utilities). CSV of concepts — codes OR plain English ('banks', 'AI'); the "
            "server resolves EACH and routes it (a GICS concept excludes the sector, a theme concept excludes the theme "
            "members), same unified resolution as `gics`. Applies to EVERY leg (fund/ta/options/dividend) — a "
            "universe-level negation, so 'high-yield stocks but NOT banks' = fundamental dividend_yield + exclude_gics='banks'. "
            "The `gics` param INCLUDES; this EXCLUDES.")] = None,
        exclude_country: Annotated[Optional[List[str]], _d("OPTIONAL — EXCLUDE operating-country(ies), ISO-2. "
            "'global ex-US' = exclude_country=['US']. Universe-level, applies to every leg.")] = None,
        exclude_theme: Annotated[Optional[List[int]], _d("ADVANCED raw-passthrough — EXCLUDE megatrend THEME node_id(s). "
            "Normally just name the theme to exclude in `exclude_gics` ('not AI'); the server routes it. Universe-level negation across every leg.")] = None,
        min_market_cap_usd: Annotated[Optional[float], _d("OPTIONAL ABSOLUTE min market cap in USD (e.g. 50000000000 = $50bn). This is an ABSOLUTE floor — distinct from `size` (which is a RELATIVE per-market tier: 'small' means small FOR ITS market, not small in USD). For 'companies under $X' / a USD band use min/max_market_cap_usd, NOT size.")] = None,
        max_market_cap_usd: Annotated[Optional[float], _d("OPTIONAL ABSOLUTE max market cap in USD (e.g. 2000000000 = under $2bn). Pair with min for a band. ABSOLUTE ceiling — use this for 'small caps under $X', not the relative `size` tier.")] = None,
        timeframe: Annotated[Optional[int], _d("Chart for the TA leg: 1=daily (default) · 2=weekly · 3=monthly. TA operand periods & for_bars are counted in BARS of this timeframe.")] = None,
        window_bars: Annotated[Optional[int], _d(
            "TA-leg LOOKBACK in BARS of `timeframe` (daily ≈ trading days) — how far back a technical signal may have "
            "fired, and the total span a THEN-chain must complete within. This is the '…within the last N days' knob: "
            "'bearish divergence within 50 days' on daily → window_bars=50. Applies to the WHOLE `ta` leg. Omit → "
            "default 30×(#steps). 🔴 SEPARATE from a fundamental trend's span (that goes in the fund condition's `N`).")] = None,
        dividend_min_streak_years: Annotated[Optional[int], _d("OPTIONAL dividend gate — keep only stocks with a "
            "no-cut dividend STREAK of at least N years (a reliability streak within a 10-year window, CAPPED at 10; "
            "10 = clean through the whole tracked decade incl. 2020/2022 stress — NOT the full multi-decade age). "
            "This is the 'dividend aristocrat / kept paying' filter. A pure MEMBERSHIP gate — combine with a "
            "`fundamental`/`ta`/`options` base leg (for a pure dividend/yield screen use screen_dividends instead).")] = None,
        dividend_min_cagr: Annotated[Optional[float], _d("OPTIONAL dividend gate — keep only stocks whose 5-year "
            "dividend CAGR is at least this % (e.g. 5 = grew dividends ≥5%/yr). Pairs with the base leg like "
            "dividend_min_streak_years; needs a `fundamental`/`ta`/`options` condition too.")] = None,
        sort: Annotated[Optional[str], _d("Rank key: 'ta' (default, TA chain score) · 'options' (the options-leg signal strength — USE THIS when `options` is present so the tight options leg DRIVES the ranking/intersection) · 'mcap' · an OSCILLATOR present in the TA context — 'rsi' (or 'rsi14') / 'adx' — to rank by that indicator's value (e.g. 'most overbought' → sort='rsi'; default direction is highest-first) · or any fundamental metric key present in the results (pe/roe/…). NOTE: an oscillator sort ranks the returned candidate buffer, so pair it with a TA filter (e.g. rsi above 60) for a meaningful 'top by RSI'.")] = None,
        limit: Annotated[Optional[int], _d("How many stocks you intend to SHOW the user (default 10). The tool "
            "over-fetches a look-ahead BUFFER of ~4× this (capped 100) and returns it all, so 'show me a few more' "
            "is served from THIS result — do NOT re-screen for a few more, just surface the next rows already here. "
            "Wanting more than the 100-row buffer needs a fresh screen with a larger intent.")] = None) -> dict:
    """EXECUTE a UNIFIED screen = universe ∩ fundamental ∩ technical ∩ options — the INTERSECTION of a fundamentals
    screen, a technical screen, and an options-behaviour screen within a scope. This is the ONE screen tool: EVERY leg
    is optional (fundamental-only = a pure fundamentals screen; ta-only = a pure technical scan of EMA/MACD cross,
    RSI/overbought, divergence, squeeze, a-THEN-b; options-only = stocks by options-market behaviour; any combination =
    the intersection). The grammars stay SEPARATE — the `fundamental` leg's `concept`/`pattern`, the `ta` leg's
    `pattern`/operands, AND the `options` leg's behaviour term are ALL resolved server-side (send a key OR plain
    English — no separate resolver step); the server resolves each leg, scopes all to the universe, and
    intersects on head_listing_id. 🔴 An options-vs-price DIVERGENCE (options positioning fighting the price trend)
    is just a multi-leg screen — send the divergence phrase in `options` and the server expands it (adds the price
    leg + opposite-direction options leg + sort='options') itself; or build it yourself by pairing a `ta` price-trend
    leg with the OPPOSITE-direction options behaviour. 🔴 The OPTIONS leg is US-optionable-only (~557 names), so any
    screen using it is US-capped — say so. To rank by options signal strength pass sort='options'. Returns {universe, count, sort,
    results:[{head_listing_id, ticker, name, score, matched_legs:[…],
              matched:{ta:{…what each signal filtered on}, fundamental:{…which value passed}},
              context:{ta:{rsi14/adx/…latest indicators}, fundamental:{…}}}], notes}.
    🔴 The per-leg subtree key == the leg NAME you sent == its `matched_legs` token: TA evidence is under
    `matched.ta` / `context.ta`, fundamental evidence under `matched.fundamental` / `context.fundamental`
    (NOT `technical` / `financial`). Read each leg's result back under the SAME name you screened on.
    🔴 TIME WINDOWS are per-LEG and SEPARATE: the TA leg's "within the last N days" = top-level `window_bars`;
    a FUNDAMENTAL trend's span (e.g. "over 2 years") = that condition's `N`. Never conflate the two.
    🔴 PARTIAL results: when NO stock matches BOTH legs (intersection < 3), the response adds `partial:true`,
    `intersection_count`, `legs:{ta,fundamental}`, and APPENDS each leg's top near-misses. Every row's `matched_legs`
    lists which leg(s) it actually passed — a row with only ['ta'] or ['fundamental'] did NOT satisfy the full query.
    NEVER present a one-leg/partial row as a full match; read `notes` (it names the tighter leg + how to broaden).
    🔴 PAGINATION / "show me more": this returns an OVER-FETCHED buffer = min(limit×4, 100) rows in ONE call, so a
    follow-up "give me a few more" is answered from the rows ALREADY in this result — do NOT call again for a few more,
    just surface the next ones you already have. `count` = rows returned in THIS response (= the buffer size, capped
    100), NOT a market-wide match total; to see more than the buffer, re-screen.
    🔴 EMPTY RESULT ≠ MISSING FEATURE. This tool FAILS LOUD: an unsupported pattern / operand / timeframe / concept
    returns a 400 ERROR. So if you got NO error and `count:0`, the query was VALID and the pattern/timeframe IS
    supported — it simply matched zero stocks right now. NEVER tell the user "the tool can't do X / X only works on
    the daily chart / that timeframe isn't supported" off a `count:0` — that conclusion requires a 400. A zero just
    means: loosen the filter, widen `window_bars` (e.g. a rare MONTHLY crossover may not have fired in the last few
    bars — widen the window), or report honestly "no stock matches that right now." (Technicals are computed
    market-wide across all timeframes — no coverage-gap disclaimer.)"""
    _lst = lambda v: None if v is None else (v if isinstance(v, list) else [v])  # forgive a client that sends a scalar
    # 🆕 SERVER-SIDE UNIFIED concept resolution (collapse find_gics + find_megatrend): `gics` / `exclude_gics` (and
    # each fundamental condition's `vs_cohort.gics`) may be a bare CODE **or** plain English ('biotech', 'AI',
    # 'not banks') → `_scope_resolve` sends it through the vector+Jev `_resolve_concept`, which decides the axis and
    # returns typed refs; we ROUTE each ref by type — gics code → the gics leg, theme node_id → merged into `theme`.
    # A pure-digit token / raw `theme` id passes straight through. Unresolved → ONE honest reconfirm. See design §15.
    scope_resolved: dict = {}
    g_codes, g_themes = [], []
    if gics:
        g_codes, g_themes, _cf, _rm = _scope_resolve(gics)
        if _cf: return _cf
        scope_resolved.update(_rm)
    xg_codes, xg_themes = [], []
    if exclude_gics:
        xg_codes, xg_themes, _cf, _rm = _scope_resolve(exclude_gics)
        if _cf: return _cf
        scope_resolved.update(_rm)
    for _c in (fundamental or []):
        if _c.vs_cohort and _c.vs_cohort.get("gics"):
            _cg, _ct, _cf, _rm = _scope_resolve(_c.vs_cohort["gics"])
            if _cf: return _cf
            _c.vs_cohort["gics"] = ",".join(_cg) if _cg else _c.vs_cohort["gics"]; scope_resolved.update(_rm)
    include: dict = {}
    if g_codes: include["gics"] = ",".join(g_codes)
    if country: include["country"] = [str(c).upper() for c in _lst(country)]
    if size: include["size"] = _lst(size)
    if asset_type: include["asset_type"] = _lst(asset_type)
    _themes = list(_lst(theme)) if theme else []
    for _t in g_themes:
        if _t not in _themes: _themes.append(_t)
    if _themes: include["theme"] = _themes
    if min_market_cap_usd is not None: include["mcap_min"] = min_market_cap_usd
    if max_market_cap_usd is not None: include["mcap_max"] = max_market_cap_usd
    excl: dict = {}
    if xg_codes: excl["gics"] = ",".join(xg_codes)
    if exclude_country: excl["country"] = [str(c).upper() for c in _lst(exclude_country)]
    _xthemes = list(_lst(exclude_theme)) if exclude_theme else []
    for _t in xg_themes:
        if _t not in _xthemes: _xthemes.append(_t)
    if _xthemes: excl["theme"] = _xthemes
    # OVER-FETCH: `limit` = how many the client means to SHOW; fetch a ~4× look-ahead buffer (cap 100) so a
    # follow-up "a few more" is served from THIS payload (in the LLM's context) with no re-screen. Beyond 100 → fresh
    # screen (a cursor-based deep-page is designed but not built — see docs/pipeline/screener-pagination-design.md).
    # ≥1 executable leg required — the screen is an INTERSECTION of fundamental ∩ ta within a scope; a scope alone
    # (gics/country/size, no leg) is a plain list, which screen_stocks serves. Guard here with a helpful redirect
    # rather than letting the API 400 (F6b: the bare-universe 400 body wasn't reaching the client clearly).
    if not fundamental and not ta and not options:
        return {"error": "screen_unified needs at least one of `fundamental`, `ta`, or `options` — it returns the "
                         "INTERSECTION of financial / technical / options-behaviour screens within a scope. For a plain "
                         "universe list (gics/country/size only, no filter) use screen_stocks instead."}
    show = _lim(limit, default=10, ceiling=100)
    fetch = min(show * 4, 100)
    body: dict = {"limit": fetch}
    if include or excl:
        u: dict = {}
        if include: u["include"] = [include]
        if excl: u["exclude"] = [excl]
        body["universe"] = u
    # 🆕 SERVER-SIDE resolution of the fundamental leg (collapse find_fsconcept + find_fspattern): each condition's
    # METRIC (concept / metricA / metricB → _resolve_fsconcept, scope field+ratio+valuation) and SHAPE (pattern /
    # relation → _resolve_fspattern) may be an exact key OR natural language → resolve here. Ambiguous / out-of-domain
    # → ONE BATCHED reconfirm (params threshold/N/… are the CLIENT's, never touched). See design §15.
    fresolved: dict = {}
    ta_resolved: dict = {}
    opt_resolved: dict = {}
    options_extra: dict = {}
    # 🆕 SERVER-SIDE resolution of the OPTIONS leg (collapse find_oppattern): the `options` term may be an exact key
    # OR plain English → resolve here. `exec_path` routes: scan → use the key; compose(live) → EXPAND the recipe's
    # legs server-side (inject its ta example + set the options pattern/sort — reuse the ta walk + assembly below, no
    # new engine); compose(pending) / unsupported / supported=no → ONE honest reconfirm (no fabrication). Runs BEFORE
    # the ta walk so an injected ta step flows through it. See design §15.
    if options:
        ro = _resolve_oppattern(options)
        if ro["status"] != "resolved":
            return {"needs_confirmation": True, "resolved": {},
                    "confirm": {ro["query"]: {"kind": "options", "status": ro["status"], "reason": ro.get("reason"), "candidates": ro.get("candidates", [])}},
                    "_guide": "The OPTIONS term needs attention: pick the right options-behaviour `pattern` from its "
                              "candidates (or drop it if `status=no_match` — it isn't a scannable options behaviour), then "
                              "RE-CALL screen_unified with the chosen key in `options` (an exact key passes straight through)."}
        _ep = ro.get("exec_path") or "scan"
        if _ep == "unsupported" or str(ro.get("supported")) == "no":
            return {"needs_confirmation": True, "resolved": {},
                    "confirm": {options: {"kind": "options", "status": "no_match", "reason": "opana can't scan this options behaviour (no such data)", "candidates": []}},
                    "_guide": "The options behaviour isn't scannable (no data) — tell the user plainly; do not substitute another pattern."}
        if _ep == "compose":
            recipe = ro.get("compose_recipe") or {}
            if str(recipe.get("status")) != "live":
                return {"needs_confirmation": True, "resolved": {},
                        "confirm": {options: {"kind": "options", "status": "pending", "reason": recipe.get("blocker") or "this composite options screen isn't wired yet", "candidates": []}},
                        "_guide": "This composite options screen isn't wired yet — tell the user plainly (see reason); do not substitute."}
            # EXPAND the live recipe: inject each non-options leg (reuse its ready `example` as a TaSignal) + set the
            # options leg to the recipe's own pattern/min_strength + adopt its sort. The injected ta step is exact
            # keys → passes through the ta walk below untouched.
            options = None
            for _leg in (recipe.get("legs") or []):
                if _leg.get("leg") == "ta" and _leg.get("example"):
                    ta = list(ta or []); ta.append(TaStep(anchor=[TaSignal(**_leg["example"])]))
                elif _leg.get("leg") == "options":
                    options = _leg.get("pattern")
                    if _leg.get("min_strength") is not None: options_extra["min_strength"] = _leg["min_strength"]
            if recipe.get("sort") and not sort: sort = recipe["sort"]
            opt_resolved[ro["query"]] = {"kind": "options", "key": ro.get("pattern"), "exec_path": "compose", "expanded_to": {"options": options, "added_ta": True, "sort": sort}, "gate": ro.get("gate")}
        else:  # scan
            if str(options).strip().lower() != str(ro.get("pattern")).lower():
                opt_resolved[ro["query"]] = {"kind": "options", "key": ro.get("pattern"), "confidence": ro.get("confidence"), "gate": ro.get("gate")}
            options = ro.get("pattern")
    if fundamental:
        fpending: list = []
        def _rc(val, kind):  # resolve one operand → key; on non-resolve append to fpending + keep the original
            if not val:
                return val
            r = _resolve_fspattern(val) if kind == "pattern" else _resolve_fsconcept(val, scope_types=("field", "ratio", "valuation"))
            key = r.get("pattern") if kind == "pattern" else r.get("key")
            if r["status"] == "resolved":
                if str(val).strip().lower() != str(key).lower():
                    fresolved[str(val)] = {"kind": kind, "key": key, "confidence": r.get("confidence"), "gate": r.get("gate")}
                return key
            fpending.append({"kind": kind, "query": r["query"], "status": r["status"],
                             "reason": r.get("reason"), "candidates": r.get("candidates", [])})
            return val
        for c in fundamental:
            if c.metricA and c.metricB and c.relation:                     # relation form (compare two metrics)
                c.metricA = _rc(c.metricA, "concept"); c.metricB = _rc(c.metricB, "concept"); c.relation = _rc(c.relation, "pattern")
            else:                                                          # common form (metric + shape)
                if c.concept: c.concept = _rc(c.concept, "concept")
                if c.pattern: c.pattern = _rc(c.pattern, "pattern")
        if fpending:
            return {
                "needs_confirmation": True,
                "resolved": fresolved,
                "confirm": {p["query"]: {"kind": p["kind"], "status": p["status"], "reason": p["reason"], "candidates": p["candidates"]} for p in fpending},
                "_guide": "Some fundamental-leg terms need attention. For each under `confirm`: `kind=concept` → pick the "
                          "right METRIC `concept` from its candidates; `kind=pattern` → pick the right SHAPE `pattern`; "
                          "`status=no_match` → that term isn't a screenable metric/shape (drop it or rephrase). Then RE-CALL "
                          "screen_unified with the chosen key(s) in the SAME conditions (exact keys pass straight through). "
                          "Leave the numeric params (threshold/N/min/max) as you had them.",
            }
        body["fundamental"] = [_cond_to_api(c) for c in fundamental]
    # 🆕 SERVER-SIDE resolution of the TA leg (collapse find_tasignal): each TaSignal's `pattern` (signals axis) and
    # operands `a`/`b` (indicators axis) may be an exact key/token OR plain English — resolve each INDEPENDENTLY
    # (design §16). A numeric/range/exact-token operand passes through untouched. Ambiguous / out-of-domain → ONE
    # BATCHED reconfirm (numeric levels + for_bars/window_bars are the CLIENT's, never touched).
    if ta:
        ta_pending: list = []
        def _rt(val, kind):  # kind: 'pattern' (signals axis) | 'operand' (indicators axis)
            if not val:
                return val
            if kind == "operand" and _is_numeric_level(val):
                return val                                                 # a numeric LEVEL / range → passthrough (not a line)
            r = _resolve_tasignal(val) if kind == "pattern" else _resolve_ta_indicator(val)
            key = r.get("pattern") if kind == "pattern" else r.get("indicator")
            if r["status"] == "resolved":
                if str(val).strip().lower() != str(key).lower():
                    ta_resolved[str(val)] = {"kind": kind, "key": key, "confidence": r.get("confidence"), "gate": r.get("gate")}
                return key
            ta_pending.append({"kind": "ta_pattern" if kind == "pattern" else "ta_indicator", "query": r["query"],
                               "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])})
            return val
        def _rsig(sig):                                                    # resolve one TaSignal in place
            sig.pattern = _rt(sig.pattern, "pattern")
            if sig.a is not None: sig.a = _rt(sig.a, "operand")
            if sig.b is not None: sig.b = _rt(sig.b, "operand")
        for step in ta:
            for sig in step.anchor:
                _rsig(sig)
            for qual in (step.quals or []):
                for sig in qual.any:
                    _rsig(sig)
        if ta_pending:
            return {
                "needs_confirmation": True,
                "resolved": ta_resolved,
                "confirm": {p["query"]: {"kind": p["kind"], "status": p["status"], "reason": p["reason"], "candidates": p["candidates"]} for p in ta_pending},
                "_guide": "Some TA-leg terms need attention. For each under `confirm`: `kind=ta_pattern` → pick the right "
                          "chart SHAPE `pattern` from its candidates; `kind=ta_indicator` → pick the right operand LINE; "
                          "`status=no_match` → that term isn't a screenable chart shape/line (drop or rephrase). Then RE-CALL "
                          "screen_unified with the chosen key(s) in the SAME ta signals (exact keys/tokens pass straight through). "
                          "Leave numeric levels + for_bars/window_bars as you had them.",
            }
        body["ta"] = [s.model_dump(exclude_none=True) for s in ta]
    if options:
        opt: dict = {"pattern": options, **options_extra}
        if options_horizon: opt["horizon"] = options_horizon
        body["options"] = opt
    if timeframe: body["timeframe"] = timeframe
    if window_bars is not None: body["window_bars"] = window_bars
    if dividend_min_streak_years is not None or dividend_min_cagr is not None:
        dv: dict = {}
        if dividend_min_streak_years is not None: dv["min_streak_years"] = dividend_min_streak_years
        if dividend_min_cagr is not None: dv["min_cagr"] = dividend_min_cagr
        body["dividend"] = dv
    if sort: body["sort"] = sort
    resp = mdx()._http._client.post("/v1/screen", json=body)
    _check(resp)
    data = resp.json()
    got = len(data.get("results", [])) if isinstance(data, dict) else 0
    if isinstance(data, dict):
        # `capped` (from the API) = the match set FILLED the fetch buffer, so `count` is a FLOOR not the true total —
        # there are more matches than returned (F8: so a client can tell "≥N" from "exactly N"). buffer_maxed = we hit
        # the hard 100 cap specifically.
        capped = bool(data.get("capped")) or got >= fetch
        data["_pagination"] = {
            "intended_show": show,
            "returned": got,
            "buffer_maxed": got >= 100,
            "capped": capped,
            "count_is_floor": capped,
            "note": (f"Over-fetched ~4× your intended show ({show}) as a look-ahead buffer so 'a few more' is served "
                     f"from these {got} rows — do NOT re-screen for a few more. "
                     + ("`count` is a FLOOR — the buffer filled, so MORE stocks match than shown; there is no exact "
                        "market-wide total (say 'at least N', or re-screen with a larger intent / tighter filter to narrow)."
                        if capped else "This is the COMPLETE match set — `count` is the exact total.")),
        }
        if fresolved: data["_resolved_fundamental"] = fresolved  # how each NL metric/shape was interpreted (transparency)
        if ta_resolved: data["_resolved_ta"] = ta_resolved
        if opt_resolved: data["_resolved_options"] = opt_resolved
        if scope_resolved: data["_resolved_scope"] = scope_resolved
    return data


_CURVE_TENORS = ("3M", "2Y", "5Y", "10Y", "30Y")
# country/bond words → ISO2, for pinning a yield-curve country from a free-text query (single tokens; matched
# against the query's word set). Only unambiguous forms — bare 2-letter ISOs (it/de/…) omitted to avoid English
# false-positives; `us`/`uk` kept (essential + safe in short bond queries).
_COUNTRY_KW = {
    "us": "US", "usa": "US", "treasury": "US", "treasuries": "US", "ust": "US", "tnote": "US",
    "germany": "DE", "german": "DE", "bund": "DE",
    "japan": "JP", "japanese": "JP", "jgb": "JP",
    "uk": "GB", "gilt": "GB", "gilts": "GB", "britain": "GB", "british": "GB",
    "france": "FR", "french": "FR", "oat": "FR",
    "italy": "IT", "italian": "IT", "btp": "IT",
    "china": "CN", "chinese": "CN", "korea": "KR", "korean": "KR",
    "australia": "AU", "australian": "AU", "canada": "CA", "canadian": "CA",
}

@mcp.tool(title="Bond Pulse", annotations=_RO)
def bond_pulse(q: Annotated[str, _dq("A COUNTRY ('US rates', 'US yield curve'), a TENOR ('US 10Y', 'JGB 2Y', "
                                         "'DE 30Y'), or a RATE ('SOFR', 'EURIBOR 3M'). Returns the whole curve + 2s10s "
                                         "slope + macro news. Covers govt-bond yields, money-market rates, and the curve.")],
               window: Annotated[Optional[str], _d(_WINDOW)] = None) -> dict:
    """⭐ "How are BONDS / RATES / the YIELD CURVE doing?" — government-bond yields (`.GB`), money-market
    rates (`.MM`), and the curve's shape (2s10s inversion). Rates are a CURVE, not a point, so this returns
    the whole picture. Give it a COUNTRY ("US rates", "US yield curve"), a TENOR ("US 10Y", "JGB 2Y"), or a
    RATE ("SOFR", "EURIBOR 3M"). Returns: the `curve` (key tenors + their yields & **bps** moves), the
    `slope` (2s10s / 10Y3M — negative = INVERTED = a classic recession signal), central-bank / macro
    `news`, and (US) `rate_positioning` — the options market on the Treasury ETFs (TLT/IEF) as a read on
    where rates are headed (ETF price↓ = yields↑, so a NEGATIVE score = positioned for HIGHER yields). 🔵 A
    yield is a LEVEL — narrate moves in BASIS POINTS, never as a % of the yield; `yield↑ ⇒ bond price↓`. The
    yield itself has no options/PE, but `rate_positioning` (bond-ETF options) answers "will rates rise?".
    Country names → translate to ISO-2 mentally (the tool resolves them). `window` scopes news recency."""
    cli = mdx()
    frm = _win(q and window)
    ms = cli._get("/v1/stocks", {"q": q, "asset_class": "bond", "limit": 8}).data.get("matches", [])
    if not ms:
        return {"error": f"no bond/rate matches '{q}'. Try 'US 10Y', 'US yield curve', 'SOFR', 'JGB 2Y'."}
    rate = next((m for m in ms if m["ticker"].endswith(".MM")), None)
    bond = next((m for m in ms if m["ticker"].endswith(".GB")), None)

    def _news_for(ticker):
        try:
            params = {"collapse": "true", "limit": 6}
            if frm:
                params["from"] = frm
            return _slim_articles(cli._get(f"/v1/stocks/{ticker}/news", params).data.get("results", []), 6)
        except Exception:
            return []

    # ── RATE mode: a money-market rate with no bond in the mix (SOFR, EURIBOR) ──
    if rate and not bond:
        t = rate["ticker"]
        try:
            p = cli._get(f"/v1/stocks/{t}/prices", {}).data
        except Exception as e:
            return {"error": f"price unavailable for {t}: {e}"}
        w = {k: {x: v[x] for x in ("change_bps",) if x in v} for k, v in (p.get("windows") or {}).items()
             if k in ("1w", "1mo", "3mo", "ytd", "1y")}
        def _rpos():
            try:
                d = cli._get("/v1/positioning", {"asset": t}).data
                return None if (not d or d.get("__notfound")) else {
                    "score": d.get("positioning_score"), "crowding": (d.get("crowding") or {}).get("state"), "read": d.get("read")}
            except Exception:
                return None
        return {"mode": "rate", "ticker": t, "name": rate.get("name"), "level": p.get("last_close"),
                "windows_bps": w, "range_read": p.get("range_read"), "news": _news_for(t), "positioning": _rpos(),
                "_guide": ("A policy/reference RATE. Narrate the level + move in BASIS POINTS (`change_bps`), "
                           "never % of the rate. Tie it to the central-bank stance in `news`. 🎯 If `positioning` "
                           "is present it's the CFTC COT futures stance (invert-aware: long future = for LOWER "
                           "rates) — weave its plain `read` in. No options/PE.")}

    # ── CURVE mode: pick the country ROBUSTLY, then pull the whole curve. A spread instrument whose NAME embeds a
    # country (e.g. `DE-US-10Y.SPREAD` = "Germany–US 10Y Spread") can top a country query and hijack this pick —
    # so derive the ISO from an explicit country WORD in the query, else a straight .GB/.MM ticker's ISO PREFIX
    # (skipping .SPREAD), and only then fall back to a non-spread match's domicile. ──
    def _iso_prefix(m):  # 'US-10Y.GB' → 'US'; None for spreads / non-curve tickers
        tk = m.get("ticker", "")
        if ".SPREAD" in tk:
            return None
        head = tk.split("-", 1)[0].split(".", 1)[0]
        return head.upper() if len(head) == 2 and head.isalpha() else None
    qtoks = set(q.lower().replace("-", " ").replace("/", " ").split())
    iso = next((c for kw, c in _COUNTRY_KW.items() if kw in qtoks), None)     # 1. a country word in the query
    if not iso:
        iso = next((p for m in ms if (p := _iso_prefix(m))), None)            # 2. a clean .GB/.MM ISO prefix
    if not iso:                                                              # 3. a non-spread match's domicile
        clean = next((m for m in ms if ".SPREAD" not in m.get("ticker", "")), ms[0])
        iso = (clean.get("domicile") or clean.get("country") or "").upper()
    if not iso or len(iso) != 2:
        return {"error": f"couldn't pin a country from '{q}'. Try 'US yield curve' / 'Germany 10Y'.",
                "matches": [{"ticker": m["ticker"], "name": m.get("name")} for m in ms[:5]]}
    tickers = [f"{iso}-{tn}.GB" for tn in _CURVE_TENORS]
    def _curve():
        try:
            res = cli._get("/v1/stocks/prices", {"tickers": ",".join(tickers)}).data.get("results", [])
            out = []
            for r in res:
                if not isinstance(r, dict) or r.get("last_close") is None:
                    continue
                # 🔴 derive the tenor from the ticker ITSELF (TH-5Y.GB → '5Y'); do NOT zip a fixed tenor list
                # positionally with res — a country with sparse coverage (TH has only 5Y/10Y) would otherwise get
                # every label shifted onto the wrong maturity (TH-5Y mislabeled '3M', TH-10Y mislabeled '2Y').
                tk = r.get("ticker", "") or ""
                tn = tk[len(iso) + 1:].split(".")[0] if tk.startswith(f"{iso}-") else tk
                out.append({"tenor": tn, "ticker": tk, "yield": r.get("last_close"),
                            "change_bps": {k: (v or {}).get("change_bps") for k, v in (r.get("windows") or {}).items()
                                           if k in ("1w", "1mo", "ytd", "1y")}})
            order = {tn: i for i, tn in enumerate(_CURVE_TENORS)}  # keep the curve in maturity order
            out.sort(key=lambda x: order.get(x["tenor"], 99))
            return out
        except Exception:
            return []
    def _slopes():
        sl = {}
        for sp in ("2s10s", "10Y3M"):
            try:
                p = cli._get(f"/v1/stocks/{iso}-{sp}.SPREAD/prices", {}).data
                v = p.get("last_close")
                sl[sp] = {"value_bps": round(v * 100, 1) if v is not None else None,
                          "inverted": (v is not None and v < 0), "read": p.get("range_read")}
            except Exception:
                pass
        return sl
    # ── rate_positioning: a yield has no options, but the US-listed Treasury ETFs (TLT 20y+, IEF 7-10y)
    #    DO — their options positioning IS the market's stance on where rates go. US-only (no clean proxy
    #    for other sovereigns in the ~547 optionable set). This is what makes "will yields rise?" answerable
    #    with a positioning lens, not just LLM cleverness reaching for TLT on its own. ──
    def _rate_positioning():
        proxies = {"US": [("TLT", "20y+ Treasuries (long end)"), ("IEF", "7-10y Treasuries (belly)")]}.get(iso)
        if not proxies:
            return {"covered": False,
                    "note": f"bond-ETF options positioning is US-only (TLT/IEF); no optionable proxy for {iso} rates."}
        etfs = []
        for sym, label in proxies:
            try:
                o = _options_brief(cli._get(f"/v1/options/{sym}/sentiment", {"style": "plain"}).data)
            except Exception as e:
                o = {"covered": False, "note": str(e)}
            etfs.append({"etf": sym, "tracks": label, **o})
        return {"covered": True,
                "note": "Bond-ETF price DOWN = long-end yields UP. So a NEGATIVE positioning_score = the "
                        "options market leaning toward HIGHER yields (bond prices falling); positive = lower.",
                "etfs": etfs}
    # ── macro_drivers: the FRED macro series that DRIVE the curve (CPI/core-PCE/jobs/unemployment/fed funds).
    #    Always relevant to "will rates rise?" → embed (US only; centralized-key + cache make it cheap). ──
    def _macro_drivers():
        if iso != "US":
            return {"covered": False, "note": "rate-drivers (CPI/jobs/fed funds) are US macro; not shown for non-US curves."}
        drv = [("CPIAUCSL", "pc1", "CPI inflation"), ("PCEPILFE", "pc1", "core PCE"),
               ("PAYEMS", "chg", "nonfarm payrolls"), ("UNRATE", "lin", "unemployment"),
               ("FEDFUNDS", "lin", "fed funds")]
        from concurrent.futures import ThreadPoolExecutor as _TPE
        with _TPE(max_workers=5) as ex2:  # `cli` captured from bond_pulse's main thread (contextvar-safe)
            return {"covered": True, "drivers": list(ex2.map(lambda t: _fred_slim(cli, t[0], t[1], t[2], "10y"), drv))}
    # ── futures_positioning: the CFTC COT basis-trade view (leveraged funds vs asset managers in the Treasury
    #    FUTURES) — complements rate_positioning (ETF options) with the second positioning lens. US tenors only. ──
    def _cot_positioning():
        if iso != "US":
            return {"covered": False, "note": "CFTC futures positioning is mapped for US Treasuries (2Y/10Y/30Y); not shown for non-US curves."}
        out = []
        for tn in ("2Y", "10Y", "30Y"):
            try:
                d = cli._get("/v1/positioning", {"asset": f"{iso}-{tn}.GB"}).data
                if d and not d.get("__notfound"):
                    out.append({"tenor": tn, "score": d.get("positioning_score"),
                                "crowding": (d.get("crowding") or {}).get("state"), "read": d.get("read")})
            except Exception:
                pass
        return {"covered": bool(out), "tenors": out}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as ex:
        fc, fs, fn, fp, fm, fcot = (ex.submit(_curve), ex.submit(_slopes), ex.submit(_news_for, f"{iso}-10Y.GB"),
                              ex.submit(_rate_positioning), ex.submit(_macro_drivers), ex.submit(_cot_positioning))
        curve, slopes, news, rate_pos, macro, cot_pos = (fc.result(), fs.result(), fn.result(),
                                                         fp.result(), fm.result(), fcot.result())
    return {
        "mode": "curve", "country": iso, "curve": curve, "slope": slopes, "news": news,
        "rate_positioning": rate_pos, "futures_positioning": cot_pos, "macro_drivers": macro,
        "_guide": ("Rates are a CURVE. LEAD with the curve's SHAPE: read `slope.2s10s` — negative = INVERTED "
                   "(a classic recession signal); positive = normal. Then the level + recent MOVE of the key "
                   "tenors in BASIS POINTS (`curve[].change_bps`, NOT %). Explain the DRIVER from `macro_drivers` "
                   "(the FRED macro that moves rates: CPI/core-PCE hot or cooling, jobs strong/weak, fed funds "
                   "stance — quote each `read`) + `news`. `yield↑ ⇒ bond price↓`. The yield itself has no "
                   "options — but for a FORWARD 'will rates rise/fall?' read, use `rate_positioning`: it's "
                   "the options market on the Treasury ETFs (TLT/IEF), where ETF price DOWN = yields UP, so a "
                   "NEGATIVE `positioning_score` = the market positioned for HIGHER yields. 🎯 `futures_positioning` "
                   "adds the CFTC COT view (leveraged funds vs asset managers in the bond FUTURES — the basis "
                   "trade; its plain `read` is invert-aware: a long future = for LOWER yields); fuse it with "
                   "rate_positioning. FUSE all — "
                   "curve move + macro_drivers + positioning: agreement strengthens the read, divergence is the "
                   "insight. Explain any options term in plain words. `covered=false` (non-US) on rate_positioning/"
                   "macro_drivers → say the US-macro/ETF proxy isn't available there. `news` empty = say so; the "
                   "curve still stands. For the FULL economy/recession read, hand off to macro_pulse."),
    }

@mcp.tool(title="Screen Stocks", annotations=_RO)
def screen_stocks(megatrend: Annotated[Optional[str], _d(_MEGATREND)] = None,
                  gics: Annotated[Optional[str], _d(_GICS)] = None,
                  country: Annotated[Optional[str], _d(_COUNTRY_CSV)] = None,
                  direction: Annotated[Optional[Literal["pos","neg"]], _d("`pos` → winners only · `neg` → losers/at-risk only · omit → all.")] = None,
                  aspect: Annotated[Optional[str], _d(_ASPECT)] = None,
                  order_by: Annotated[Optional[Literal["news_count","relevance","market_cap"]], _d("`news_count` (default, most attention) | `relevance` | `market_cap`.")] = None,
                  min_impact: Annotated[Optional[int], _d("Min article importance, 1–5.")] = None,
                  min_relevance: Annotated[Optional[float], _d("Min centrality to its news, 0–1.")] = None,
                  min_market_cap_usd: Annotated[Optional[float], _d("Min market cap, USD.")] = None,
                  window: Annotated[Optional[str], _d(_WINDOW)] = None,
                  from_: Annotated[Optional[str], _d("Start date YYYY-MM-DD. ⚠️ per-stock impact scoring only exists from ~2026-07-03 (earlier → empty).")] = None,
                  to: Annotated[Optional[str], _d(_TO)] = None,
                  gate: Annotated[Optional[str], _d("megatrend scope only: `both` (default, strict member AND epicenter) | `membership` (looser).")] = None,
                  limit: Annotated[Optional[int], _d(_LIMIT)] = None) -> dict:
    """⭐ "Which stocks in <a group> are INTERESTING / winning / losing / most-talked-about — and how
    CHEAP or EXPENSIVE do they trade?" — the cohort SCREENER. Ranks the companies in a scope by how the news
    is hitting them (lead with the WINNERS-vs-LOSERS split), AND every row carries its **VALUATION** (P/E,
    P/B, dividend yield, 52w) — so this is ALSO the tool for "which in <group> are cheap / EU-vs-US banks on
    P/E–P/B / is <cohort> worth investing". 💰 A valuation / "worth investing" / cheap-vs-expensive question
    on a GROUP → screen here and READ the fundamentals; theme_pulse/brief are NEWS pulse only (no valuation),
    so never say "I don't have P/E" — pull it from here (P/B is best-covered; for banks/insurers P/B leads).
    ⚠️ these rows are a NEWS-RANKED, CAPPED SUBSET of the group — NOT the full cohort. Do NOT compute a
    "sector/peer AVERAGE" (P/E, margin, ROE…) from them to judge cheap-vs-peers: that average is a tiny biased
    sample, unweighted, and includes bad-data outliers → wrong. For "cheaper/richer than the sector/peer AVERAGE",
    "below/above the group average", or "undervalued vs peers" → use **screen_unified** with a `fundamental` pattern
    `below_average`/`above_average` (a proper cap-weighted, full-universe, outlier-cleaned benchmark).
      • Scope (≥1 REQUIRED — it never scans the whole universe): `megatrend` (one OR SEVERAL trend
        names/ids as csv — resolved for you in one pass, same as theme_pulse: 'foundry', 'foundry,hbm',
        '56020000'), `gics` (a GICS sector/industry — codes OR plain English, CSV; server resolves each:
        'semis'/'453010', 'retail'/'2550', 'aerospace defense', 'biotech'), `country` (csv ISO-2; for a REGION pass every
        country — Asia='CN,JP,KR,TW,HK,IN,SG'). Combine freely — "China+Taiwan foundry & HBM names" = ONE
        call: country='CN,TW', megatrend='foundry,hbm'.
      • `order_by` = `news_count` (default — most attention) | `relevance` (most central to its news) |
        `market_cap` (biggest).
      • `direction` = `pos` → winners only · `neg` → losers/at-risk only · omit → all, each with its own
        net_direction. `aspect` = keep only a channel (demand/competition/capital/…).
      • Quality floors: `min_impact` (1–5 article-importance), `min_relevance` (0–1 centrality),
        `min_market_cap_usd`, `window` ('7d'/'30d'/'90d'/'1y'/'mtd'/'qtd'/'ytd'). `gate` (megatrend scope
        only) = `both` (default, strict: member AND epicenter) | `membership` (looser, more leakage).
      • TIME WINDOW: `window='7d'` = trailing recency ("this week"=7d, "this month"=30d) — SAME name/vocab
        as brief/theme_pulse/search_news/news_feed/stock_impact. For a SPECIFIC past
        window use `from`/`to` (YYYY-MM-DD): "last week"→the two dates, "as of <date>"→`to`. ⚠️ per-stock
        IMPACT scoring only exists from ~2026-07-03 onward, so any window BEFORE early-July-2026 (a Q1/March
        query) returns EMPTY — say so plainly ("no impact data that far back"); do NOT present empty as
        "nothing happened".
    Each row = `{symbol, name, country, gic_code, market_cap_usd, impact:{news_count, pos, neg, ambiguous,
    net_direction, top_relevance, aspects, top_reason}, fundamentals:{pe_ratio, pb_ratio, dividend_yield_pct,
    week52_high, week52_low}}` — the `fundamentals` block is the VALUATION lens (read it for cheap/expensive).
    Each row carries `market_cap_usd`, so for a
    constraint we DON'T support (e.g. "SMALL-cap only", a max size) return the cohort and filter/annotate
    from that field + your own knowledge. `direction_split` pre-tallies the cohort's winners/losers so you
    can open with it. If a scope term isn't a MarketDX taxonomy node (a niche theme like 'protein
    engineering'), map it to the nearest `gics`/`country` you CAN pass and lean on your world knowledge for
    the rest. For ONE ticker use `asset_pulse`; for a sector's overall pulse use `theme_pulse`; use THIS to
    rank the NAMES inside a group. `limit` default 10 (max 50)."""
    mt = None
    if megatrend:  # UNIFIED: theme term(s) → megatrend node ids
        mt, _me = _theme_nodes(megatrend)
        if _me: return _me
    if gics:  # UNIFIED: gics code(s) OR plain English; a theme concept flows into the megatrend leg
        _g, _t, _cf, _ = _scope_resolve(gics)
        if _cf: return _cf
        gics = ",".join(_g) if _g else None
        if _t:
            mt = ",".join([str(x) for x in _t] + ([mt] if mt else []))
    if not (mt or gics or country):
        return {"error": "screen_stocks needs at least one scope: megatrend (a theme name/id), gics (a sector name/code), or country."}
    params = {"megatrend": mt, "gics": gics, "country": country, "direction": direction,
              "aspect": aspect, "order_by": order_by, "min_impact": min_impact,
              "min_relevance": min_relevance, "min_market_cap_usd": min_market_cap_usd,
              "window": window, "from": from_, "to": to,
              "gate": gate, "limit": _lim(limit, default=10, ceiling=50)}
    rows = mdx()._get("/v1/stocks", params).data.get("stocks", [])
    keep = ("stock_id", "symbol", "ticker", "name", "country", "gic_code", "market_cap_usd", "impact", "fundamentals")
    stocks = [{k: r[k] for k in keep if k in r} for r in rows]
    def _nd(r):
        return ((r.get("impact") or {}).get("net_direction")) or "n/a"
    split = {"total": len(stocks),
             "net_positive": sum(1 for r in stocks if _nd(r) == "pos"),
             "net_negative": sum(1 for r in stocks if _nd(r) == "neg"),
             "ambiguous": sum(1 for r in stocks if _nd(r) == "ambiguous")}
    # echo the RESOLVED megatrend node name(s) — a bare `megatrend` NAME auto-resolves to node id(s) via
    # _theme_nodes (the unified Jev resolver); surface WHICH node(s) so the client isn't guessing.
    mt_named = None
    if mt:
        tax = _taxonomy()["by_id"]
        mt_named = [{"id": int(i), "name": tax[int(i)]["name"]} for i in str(mt).split(",")
                    if i.strip().isdigit() and int(i) in tax] or None
    return {
        "scope": {k: v for k, v in {"megatrend": mt, "megatrend_resolved": mt_named,
                                    "gics": gics, "country": country}.items() if v},
        "order_by": order_by or "news_count", "direction": direction,
        "direction_split": split, "stocks": stocks,
        "_guide": ("LEAD with the winners-vs-losers split (`direction_split` + each row's `impact."
                   "net_direction` with its pos/neg counts), NOT a flat ranked dump. Surface any "
                   "net-NEGATIVE standouts SEPARATELY — they're the contrarian / at-risk names. For each "
                   "name explain WHY it's interesting from its `impact.top_reason` + `aspects` (the "
                   "channels), not just that it ranks high. If a name has high news_count but a large neg "
                   "count too, call it CONTESTED. Each row also carries `fundamentals` (dividend_yield_pct, "
                   "pe_ratio, pb_ratio, 52w range) — a MATRIX: weave the facet that fits the group (income "
                   "yield for retail/utilities/banks, valuation for value plays; ignore for pure-growth/AI "
                   "names that don't pay). For a dedicated income rank use `screen_dividends`. "
                   "Research-analyst voice — observations, not advice."),
    }

@mcp.tool(title="Screen Dividends", annotations=_RO)
def screen_dividends(country: Annotated[Optional[str], _d(_COUNTRY_CSV)] = None,
                     gics: Annotated[Optional[str], _d(_GICS)] = None,
                     min_yield: Annotated[Optional[float], _d("Min dividend yield in PERCENT (3 = 3%).")] = None,
                     max_yield: Annotated[Optional[float], _d("Max yield % — guards against trap-tier yields.")] = None,
                     min_streak_years: Annotated[Optional[int], _d("Min no-cut streak years (0–10; caps at 10 = clean across the "
                                                                   "whole tracked decade). HIGHER = more reliable. A low bar lets "
                                                                   "a name that CUT recently through — it may have only rebuilt a "
                                                                   "short streak since its `last_cut_year`, so a short streak ≠ "
                                                                   "'stable'. The stronger the 'safe / stable / hold-for-years' "
                                                                   "intent, the closer to the cap you should set it.")] = None,
                     min_cagr: Annotated[Optional[float], _d("Min 5-year dividend CAGR, %.")] = None,
                     min_market_cap_usd: Annotated[Optional[float], _d("Min market cap, USD.")] = None,
                     max_market_cap_usd: Annotated[Optional[float], _d("Max market cap, USD.")] = None,
                     max_payout: Annotated[Optional[float], _d("Max payout ratio — 'high yield but payout NOT stretched'. "
                                                               "Fraction (0.7) or percent (70).")] = None,
                     order_by: Annotated[Optional[Literal["yield","streak","cagr"]], _d("`yield` (default) | `streak` | `cagr`.")] = None,
                     limit: Annotated[Optional[int], _d(_LIMIT)] = None) -> dict:
    """💰 THE income screener — "which stocks in <a group> pay a high / reliable / growing DIVIDEND?"
    ("retail names with high dividend", "dividend aristocrats in the US", "Thai high-yield stocks"). Ranks
    the DIVIDEND-PAYING universe (all payers, NOT just news-covered) and — the whole point — hands you the
    RAW pieces to tell a real income name from a YIELD TRAP, so YOU judge (don't trust a headline yield).
    🔴 MULTI-METRIC dividend asks (dividend AND low P/E AND exclude a sector AND healthy financials) belong in
    screen_unified — a `fundamental` leg (pe / health / dividend_yield) + the `dividend_min_streak_years` /
    `dividend_min_cagr` gate. THIS tool is the dividend SPECIALIST (yield ranking + no-cut streak + yield-trap
    decomposition): it has NO P/E filter and `gics` only INCLUDES a sector (it can't EXCLUDE banks).
      • Scope (≥1 REQUIRED): `country` (csv ISO-2) and/or `gics` (csv GICS CODE prefixes, e.g. '2550' retail).
        Pass a sector as a CODE or plain English ('banks'); the server resolves it. Combine freely.
      • `order_by` = `yield` (default) | `streak` (reliability — longest clean run in our window) | `cagr`
        (fastest dividend growth). Filters: `min_yield`/`max_yield` (PERCENT, e.g. 3 = 3%; max guards against
        traps), `min_streak_years` (≤10, see below), `min_cagr` (%), `min/max_market_cap_usd`, `max_payout`
        (ceiling on payout_ratio — high yield with payout ≤ this = safer, not stretched).
    🔴 `no_cut_streak_yrs` is a bounded RELIABILITY signal — consecutive no-cut years within a **10-year**
    tracking window, so it CAPS AT 10 (10 = never cut across the whole decade, i.e. survived the 2020 &
    2022 stress). It is NOT the company's full dividend age: DO NOT report "~50-year king / 69-year streak"
    or any multi-decade figure from your own knowledge — say "clean for 10y+ (the full window we track)".
    Each row's `dividend` block DECOMPOSES the yield: `yield_pct` (FORWARD/sustainable — what to quote),
    `yield_trailing_pct` (if >> yield_pct, a SPECIAL one-time dividend inflated it — not repeatable),
    `payout_ratio` (>1 = pays more than it earns = unsustainable), `ttm_div_yoy_pct` (is the PAYMENT up/flat/
    CUT), `no_cut_streak_yrs` (≤10, reliability not age), `last_cut_year`, `cagr_5y_pct` — plus `week52_high/low` (is the yield high
    because the PRICE fell?) + `pe_ratio`/`pb_ratio`/`eps` + a `news` block. 🔴 NEVER rank on yield alone: high yield +
    recent `last_cut_year` + negative `ttm_div_yoy_pct` + high payout + bad `news` = TRAP; high yield from a
    price drop + intact/growing dividend + long streak = possible VALUE. Read the payload's `_guide`.
    `limit` default 15 (max 50). SCOPE (country/gics) is OPTIONAL — omit both to rank dividend payers
    WHOLE-MARKET (the candidate scan is bounded + fast); add a scope to narrow to one market/sector."""
    if gics:  # UNIFIED: gics code(s) OR plain English. gics-ONLY tool — a theme concept can't be screened here (honest)
        _g, _t, _cf, _ = _scope_resolve(gics)
        if _cf: return _cf
        if _t and not _g:
            return {"needs_confirmation": True, "not_a_sector": True, "query": gics,
                    "_guide": f"'{gics}' resolved to a curated THEME, not a GICS sector — screen_dividends screens by "
                              f"sector only. Use screen_unified(gics='{gics}') with a dividend gate for a theme scope."}
        gics = ",".join(_g) if _g else None
    params = {"country": country, "gics": gics,
              "min_yield": min_yield, "max_yield": max_yield,
              "min_streak_years": min_streak_years, "min_cagr": min_cagr,
              "min_market_cap_usd": min_market_cap_usd, "max_market_cap_usd": max_market_cap_usd,
              "max_payout": max_payout,
              "order_by": order_by, "limit": _lim(limit, default=15, ceiling=50)}
    return mdx()._get("/v1/stocks/dividends", params).data


# ── Trade & Customs (UN Comtrade) — international merchandise + services trade flows ─────────────────
# There is NO find_hs tool — the 4 trade tools (search_trade/top_partners/top_traders/trade_balance) resolve a good/
# service CONCEPT (or an exact HS/EBOPS code) in their `codes` server-side via _resolve_hs (vector /v1/ext/hs/find →
# Jev pick → gate), picking the right SUPPLY STAGE. The query tools are BYOK (the user's own Comtrade key, metered
# Flat(5)). See docs/product/mcp-trade-tools-design.md (Ava repo) for the entity→trade bridge + gate hierarchy.
_HS_RESOLVE_INSTR = (
    "The state has `query`: a tradable GOOD or SERVICE concept the user wants a trade CODE for (possibly the form "
    "'Resolve the entity \"X\" as it is used in the user's request: \"<full request>\"' — resolve X using that "
    "CONTEXT). Each option is a candidate code: its title, the `excl:` note (which NAMES the sibling codes, i.e. the "
    "other supply-chain STAGES), and its 4-digit parent. Pick the SINGLE code the request MEANS, at (1) the right "
    "SUPPLY STAGE — for a raw material the same word spans ORE/concentrate vs unrefined vs REFINED vs scrap; the "
    "`excl:` note tells them apart ('copper ore' → the ore code, whose excl names 'refined copper cathodes'; 'refined "
    "copper' → the refined one) — and (2) the right GRANULARITY: a SPECIFIC product → its leaf code; a BROAD / 'all X "
    "/ the whole <material>' request → the matching 'ALL of HS <parent>' roll-up option (the whole 4-digit family, "
    "Comtrade-aggregated, e.g. all rice → 1006; semiconductor devices → the 8541 family / integrated circuits → 8542) "
    "rather than one arbitrary leaf. One option is `__NONE__` — choose it ONLY when the query is NOT a tradable "
    "good/service at all.")
_HS_NONE_OPT = (
    "None of the candidates is the trade code the query means. ⚠️ LAST RESORT — pick this ONLY when the query is not a "
    "tradable good/service at all (a non-trade concept, a company, a market price, gibberish), OR it is clearly the "
    "WRONG type for this request (a SERVICE searched among goods codes, or vice-versa). A real tradable good/service "
    "that DOES match a candidate must resolve to it, never to NONE.")
_HS_CODES = ("Product/service CODE(s) OR CONCEPT(s). A numeric HS/EBOPS code (`2709`, or `0207,0203` for a basket) "
             "passes straight through; a plain CONCEPT ('crude oil', 'copper ore', 'ทองแดง', 'semiconductors') is "
             "resolved server-side to the code at the right SUPPLY STAGE (ore vs refined). Several entries = merged; a "
             "4-digit code aggregates the whole family. A stage-ambiguous concept comes back as a reconfirm to pick from.")
_HS_CTX = ("OPTIONAL but RECOMMENDED — the user's FULL request VERBATIM (any language). Used to pick the right code + "
           "SUPPLY STAGE (ore vs concentrate vs refined) and leaf-vs-family granularity for a `codes` concept.")

def _is_hs_code(s: str) -> bool:
    """An exact HS/EBOPS code already in hand → passthrough (skip resolve): a numeric token (HS 2–8 digits, EBOPS
    3-digit). A concept ('crude oil', 'ทองแดง') → resolve."""
    s = (s or "").strip()
    return bool(s) and s.replace(".", "").isdigit()

def _hs_prep(q: str, type: str = "goods", context: Optional[str] = None) -> dict:
    """PREP (retrieval + exact passthrough + options + 4-digit roll-up) for an HS resolution — NO Jev. Returns a
    TERMINAL dict (status set) or a `_pending` dict {jev_q, type, options, meta} to feed one/ batched Jev pick.
    Resolve ONE good/service concept → the exact trade CODE (HS goods / EBOPS services) at the right supply stage.
    Mirrors _resolve_series: exact code → passthrough; else vector shortlist (/v1/ext/hs/find, full context:
    title+excludes+parent) → Jev pick (judged by `context`) + `__NONE__` → calibrated gate. Returns
    {status, query, code?, title?, parent_code?, confidence?, gate?, note?, candidates?}."""
    cands = _bget("/v1/ext/hs/find", {"q": q, "type": type, "limit": 15})
    cands = cands.get("candidates") or (cands if isinstance(cands, list) else [])
    if not cands:
        return {"status": "no_match", "query": q, "reason": f"no candidate {type} codes", "candidates": []}
    exact = next((c for c in cands if str(c.get("code", "")).lower() == q.strip().lower()), None)
    if exact:
        return {"status": "resolved", "query": q, "code": exact["code"], "title": exact.get("title"),
                "parent_code": exact.get("parent_code"), "confidence": 1.0, "gate": "exact_key"}
    options, meta = {}, {}
    for c in cands:
        code = c.get("code")
        if not code:
            continue
        desc = c.get("title") or code
        excl = c.get("excludes")
        if excl:
            desc += " — excl: " + ("; ".join(excl) if isinstance(excl, list) else str(excl))
        if c.get("parent_code"):
            desc += f" (parent {c['parent_code']})"
        options[code] = desc
        meta[code] = {"code": code, "title": c.get("title"), "parent_code": c.get("parent_code")}
    # ROLL-UP: a 4-digit PARENT with ≥2 leaf children in the shortlist becomes a pickable synthetic option ("all
    # <family>", Comtrade-aggregated) — so an "all X / whole family" request resolves to the aggregate code (all rice
    # → 1006), which the OLD find_hs client had to roll up to manually via `parent_code`.
    fam: dict = {}
    for c in cands:
        pc = c.get("parent_code")
        if pc and str(pc) != str(c.get("code")):
            fam.setdefault(str(pc), []).append(c.get("title") or c.get("code"))
    for pc, kids in fam.items():
        if len(kids) >= 2 and pc not in options:
            options[pc] = f"ALL of HS {pc} — the WHOLE 4-digit family (Comtrade aggregates it); covers e.g.: " + "; ".join(kids[:4])
            meta[pc] = {"code": pc, "title": f"HS {pc} (whole family)", "parent_code": pc}
    options["__NONE__"] = _HS_NONE_OPT
    jev_q = (f'Resolve the entity "{q}" as it is used in the user\'s request: "{context.strip()}"'
             if context and context.strip() and context.strip().lower() != q.strip().lower() else q)
    return {"_pending": True, "query": q, "jev_q": jev_q, "type": type, "options": options, "meta": meta}

def _hs_finish(prep: dict, r: dict) -> dict:
    """Gate + shape a Jev pick `r` for a prepared HS resolution — shared by the single and BATCH paths."""
    q, meta, typ = prep["query"], prep["meta"], prep["type"]
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": f"not a tradable {typ} concept (Jev: none fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"code": meta[k]["code"], "title": meta[k]["title"], "parent_code": meta[k]["parent_code"],
                  "prob": round(v, 3)} for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "code": pm.get("code"), "title": pm.get("title"),
               "parent_code": pm.get("parent_code"), "confidence": r.get("confidence"), "gate": gate}
        if gate == "soft":
            alts = ", ".join(c["code"] for c in top_cands[1:3])
            out["note"] = f"resolved '{q}' → {pm.get('code')} at lower confidence; alternatives: {alts}"
        return out
    reason = "different products or supply stages — confirm which" if gate == "reconfirm" else "no confident trade-code match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

def _hs_batch_instr(prep: dict) -> str:
    """Instructions for a BATCH HS pick entry — resolve instr + the entity/context (state.query is shared in a batch)."""
    return _HS_RESOLVE_INSTR + "\n\nRESOLVE THE ENTITY DESCRIBED HERE: " + prep["jev_q"]

def _resolve_hs(q: str, type: str = "goods", context: Optional[str] = None) -> dict:
    """Resolve ONE good/service concept → the exact trade CODE (SINGLE path — unchanged): prep → one Jev pick → gate."""
    prep = _hs_prep(q, type, context)
    if not prep.get("_pending"):
        return prep
    r = _jev_pick(prep["jev_q"], _HS_RESOLVE_INSTR, prep["options"])
    return _hs_finish(prep, r)

def _hs_codes_arg(vals, type: str = "goods", context: Optional[str] = None):
    """Plural — resolve a list/CSV of trade `codes` → (codes:list, confirm|None, detail). A numeric token passes through;
    concepts are resolved in ONE batched Jev call with their retrievals fanned out in parallel; ANY pending → ONE
    batched reconfirm (kind='hs'). Token order preserved in the output."""
    if not vals:
        return [], None, {}
    toks = [str(t).strip() for t in (vals if isinstance(vals, list) else str(vals).split(",")) if str(t).strip()]
    detail, pend, resolved = {}, {}, {}   # resolved: tok -> code (preserves input order at assembly)
    def _record(tok, r):
        if r["status"] == "resolved":
            resolved[tok] = r["code"]; detail[tok] = {"code": r.get("code"), "title": r.get("title"), "gate": r.get("gate")}
        else:
            pend[tok] = {"kind": "hs", "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])}
    prepped, concept_toks = {}, []
    for tok in toks:
        if _is_hs_code(tok):
            resolved[tok] = tok                              # exact code — dual-mode passthrough, no retrieval/Jev
        else:
            concept_toks.append(tok)
    if concept_toks:                      # 🆕 PARALLEL retrieval — independent /v1/ext/hs/find GETs, no serial loop
        mdx()
        with _futures.ThreadPoolExecutor(max_workers=min(8, len(concept_toks))) as ex:
            preps = list(ex.map(lambda t: _hs_prep(t, type, context), concept_toks))
        for tok, prep in zip(concept_toks, preps):
            if prep.get("_pending"):
                prepped[tok] = prep
            else:
                _record(tok, prep)                           # exact passthrough / no_match — no Jev
    if prepped:                           # 🆕 BATCH — ALL pending concepts in ONE Jev call (was one per token)
        qmap = {tok: {"instructions": _hs_batch_instr(p), "options": p["options"]} for tok, p in prepped.items()}
        picks = _jev_picks(qmap, state_query="")
        for tok, p in prepped.items():
            _record(tok, _hs_finish(p, picks.get(tok) or {}))
    if pend:
        return [], {"needs_confirmation": True, "resolved": detail, "confirm": pend,
                    "_guide": "A product/service isn't a unique trade code — pick a `code` from candidates (mind the "
                              "SUPPLY STAGE: ore vs refined), or refine the concept / add `context`, then re-call (a "
                              "numeric HS/EBOPS code passes straight through)."}, detail
    return [resolved[t] for t in toks if t in resolved], None, detail

@mcp.tool(name="search_trade", title="Trade Flows Over Time", annotations=_RO)
def search_trade(reporter: Annotated[str, _d("Reporting country — name / ISO / M49 (`Thailand`/`THA`/`764`); resolved server-side.")],
                 codes: Annotated[Union[List[str], str], _d(_HS_CODES)],
                 partner: Annotated[Optional[str], _d("Partner country, or `World` (default) = all combined.")] = None,
                 flow: Annotated[Optional[Literal["export","import","both"]], _d("`export` (default) | `import` | `both`.")] = None,
                 period: Annotated[Optional[str], _d("`last10` annual / `last12` monthly (default) · a year `2023` · list `2020,2021` · range `2015:2024` · `latest`. DYNAMIC — never hardcode a year.")] = None,
                 type: Annotated[str, _d("`goods` (default, HS) | `services` (EBOPS — VALUE-ONLY: no volume/price axes, no mirror).")] = "goods",
                 freq: Annotated[Optional[str], _d("`annual` (default) | `monthly` (YYYYMM, fresher; goods only).")] = None,
                 mirror: Annotated[Optional[bool], _d("Also return the partner-REPORTED figure + `discrepancy` (FOB/CIF gap). Use for China esp. / when quoting a precise number. Goods only.")] = None,
                 context: Annotated[Optional[str], _d(_HS_CTX)] = None) -> dict:
    """One trade FLOW over time (BYOK, 5 credits) — "how much <product> did <A> export to <B>?". Returns
    `series` (per-period value_usd / netweight / qty) PLUS an `analysis` block (decomposed like our
    price-features: value / volume / unit-price each with trend / cagr_pct / peak / trough / biggest_swing, +
    a `decomposition` = is a change price- or volume-driven). LEAD with `analysis`; don't re-derive from the
    raw series. `mirror=true` adds the partner's figure + discrepancy. A GAP in old years may be an HS-revision
    break, NOT zero trade. `netweight_kg`/`qty` are often NULL for the LATEST year (value reported first) — that
    is NORMAL, read value-only, don't re-fetch. Pass ONE product line per call (merging unlike codes muddies the
    decomposition/`analysis`). Surface `_license_note` when showing data. ~1 req/sec server-paced — don't fan out.
    BYOK: no key → an `error`/`note` with a connect CTA (relay it; you may answer from general knowledge
    meanwhile)."""
    codes_r, cf, _det = _hs_codes_arg(codes, type=type, context=context)  # 🆕 collapse find_hs (concept OR code)
    if cf: return cf
    return _ext("/v1/ext/comtrade/search",
                {"reporter": reporter, "codes": codes_r, "partner": partner, "flow": flow,
                 "period": period, "type": type, "freq": freq, "mirror": mirror})

@mcp.tool(name="top_partners", title="Top Trade Partners", annotations=_RO)
def top_partners(reporter: Annotated[str, _d("Reporting country — name / ISO / M49.")],
                 codes: Annotated[Union[List[str], str], _d(_HS_CODES)],
                 flow: Annotated[Optional[Literal["export","import","both"]], _d("`export` (default) → biggest BUYERS · `import` → biggest SUPPLIERS · `both`.")] = None,
                 period: Annotated[Optional[str], _d("Default `latest`; a year / list / range / `lastN`. Dynamic.")] = None,
                 type: Annotated[str, _d("`goods` (default) | `services`.")] = "goods",
                 limit: Annotated[Optional[int], _d("Top-N partners (default 10, max 50).")] = None,
                 context: Annotated[Optional[str], _d(_HS_CTX)] = None) -> dict:
    """"Who buys/sells <a GIVEN country>'s <product>?" (BYOK, 5cr). Ranks that reporter's partners →
    `ranked:[{partner, value_usd, share_pct}]` + `total_value_usd`. flow=export → biggest BUYERS; import →
    biggest SUPPLIERS. (Ranks the PARTNERS of ONE country — vs `top_traders`, which ranks the countries
    themselves.) BYOK note relayed on 402."""
    codes_r, cf, _det = _hs_codes_arg(codes, type=type, context=context)  # 🆕 collapse find_hs
    if cf: return cf
    return _ext("/v1/ext/comtrade/top-partners",
                {"reporter": reporter, "codes": codes_r, "flow": flow, "period": period,
                 "type": type, "limit": _lim(limit, default=10, ceiling=50)})

@mcp.tool(name="top_traders", title="Rank Countries by Trade", annotations=_RO)
def top_traders(codes: Annotated[Union[List[str], str], _d(_HS_CODES + " GOODS only — SUMMED per country.")],
                flow: Annotated[Optional[Literal["export","import","both"]], _d("`import` (default) | `export` | `both`.")] = None,
                scope: Annotated[Optional[str], _d("`world` (default) · continent (`asia`/`europe`/`africa`/`americas`/`oceania`) · subregion · econ group (`asean`/`eu`/`g7`) · CSV of ISO-2. (Region is OUR layer.)")] = None,
                rank_by: Annotated[Optional[str], _d("`value` (default, period sum) · `growth` (CAGR, ≥2 periods) · `streak` (consecutive-move run, ≥2).")] = None,
                order: Annotated[Optional[str], _d("value/growth → `desc`(default)/`asc` · STREAK → run direction (`desc`=consecutive INCREASES, `asc`=DECREASES).")] = None,
                period: Annotated[Optional[str], _d("Dynamic. Defaults: value=`latest`, growth=`last5`, streak=`last10`.")] = None,
                limit: Annotated[Optional[int], _d("Top-N (default 10, max 50).")] = None,
                min_value_usd: Annotated[Optional[float], _d("Floor to drop tiny-base noise (growth/streak default 1e6).")] = None,
                context: Annotated[Optional[str], _d(_HS_CTX)] = None) -> dict:
    """⭐ Rank COUNTRIES by their trade of a product, in ONE call (BYOK, 5cr; GOODS only) — "which country
    imports/exports the most / grows fastest / declines / rose N years straight". `codes` are summed per
    country; `scope` narrows to a region/bloc. `rank_by`: `value` → {rank,partner,value_usd,share_pct} ·
    `growth` → {…,cagr_pct,total_change_pct,from,to} · `streak` → {…,streak_years,direction,from,to}.
    ⚠️ growth/streak spans can differ per country — CAGR annualizes so the ranking is fair; state the real
    `from`/`to` years from the payload. "#2 exporter" = the rank:2 row. "BOTH X and Y up 5y" → call per
    commodity and INTERSECT the lists yourself. An empty/short list = a real answer; relay it, don't fabricate."""
    codes_r, cf, _det = _hs_codes_arg(codes, type="goods", context=context)  # 🆕 collapse find_hs (goods only)
    if cf: return cf
    return _ext("/v1/ext/comtrade/top-traders",
                {"codes": codes_r, "flow": flow, "scope": scope, "rank_by": rank_by, "order": order,
                 "period": period, "limit": _lim(limit, default=10, ceiling=50), "min_value_usd": min_value_usd})

@mcp.tool(name="trade_balance", title="Trade Balance", annotations=_RO)
def trade_balance(reporter: Annotated[str, _d("Reporting country — name / ISO / M49.")],
                  partner: Annotated[Optional[str], _d("Partner country, or `World` (default).")] = None,
                  codes: Annotated[Optional[Union[List[str], str]], _d("For a PRODUCT balance: HS code(s) OR a CONCEPT (resolved server-side at the right stage). OMIT → `TOTAL` (all commodities, a macro read). GOODS only.")] = None,
                  period: Annotated[Optional[str], _d("Default `latest`; a year / list / range / `lastN`. Dynamic.")] = None,
                  context: Annotated[Optional[str], _d(_HS_CTX)] = None) -> dict:
    """Exports vs imports vs NET balance (BYOK, 5cr; GOODS only) — "is <A> a net exporter to <B> (of <X>)?".
    Returns `rows:[{year, exports_usd, imports_usd, balance_usd}]` (balance = exports − imports; + = surplus).
    `codes` defaults to TOTAL (all commodities) for a macro/country read; pass an HS code OR a product concept for one
    product. 🔎 CHECK the `basis` field in the response — it says whether you got a `commodity-specific` balance
    or the all-commodity `TOTAL`; if you meant a product balance but `basis` says TOTAL, you forgot `codes`.
    ⭐ Signature use for TARIFF / trade-war news (US↔China): pull the actual balance to quantify what the
    news sentiment only gestures at. BYOK note relayed on 402."""
    codes_out = "TOTAL"
    if codes:                                              # 🆕 collapse find_hs (a PRODUCT balance — concept OR code)
        codes_r, cf, _det = _hs_codes_arg(codes, type="goods", context=context)
        if cf: return cf
        codes_out = codes_r or "TOTAL"
    return _ext("/v1/ext/comtrade/balance",
                {"reporter": reporter, "partner": partner, "codes": codes_out, "period": period})

# ── Macro (FRED) — economic time series + regime/dashboard reads ─────────────────────────────────────
# There is NO find_series tool — fred_series resolves a macro concept (or an exact series_id) server-side via
# _resolve_series (vector /v1/ext/fred/find → Jev pick → gate), carrying the RIGHT transform. macro_pulse = dashboards.
# Centralized key + cross-user cache server-side (no BYOK). Design: docs/product/macro-pulse-design.md.
_SERIES_RESOLVE_INSTR = (
    "The state has `query`: a macro concept the user wants a FRED time series for (possibly the form 'Resolve the "
    "entity \"X\" as it is used in the user's request: \"<full request>\"' — resolve X using that CONTEXT). Each option "
    "is a candidate FRED series: its title, units/frequency/seasonal-adjustment, the suggested transform, and whether "
    "it is curated. Pick the SINGLE series the request MEANS. Disambiguate by intent: HEADLINE vs CORE (CPIAUCSL / all-"
    "items vs CPILFESL / PCEPILFE ex-food-energy — 'core' → the ex-food-energy one); the price INDEX vs a market "
    "BREAKEVEN/expectation (CPIAUCSL vs T10YIE); SA vs NSA; PCE vs CPI; a RATE/level series vs a stock. Prefer the "
    "`curated` / canonical series when the request is generic ('inflation' → the headline CPI). One option is "
    "`__NONE__` — read its description; choose it ONLY when the query is NOT a FRED macro series at all.")
_SERIES_NONE_OPT = (
    "None of the candidates is the FRED macro series the query means. ⚠️ LAST RESORT — pick this ONLY when the query is "
    "not a FRED time series at all (a survey diffusion index like ISM/PMI that FRED doesn't carry; a commodity SPOT "
    "price → belongs in commodity_pulse; a single company; gibberish). A real macro concept that DOES match a "
    "candidate must resolve to it, never to NONE.")

def _resolve_series(q: str, country: Optional[str] = None, context: Optional[str] = None) -> dict:
    """Resolve ONE macro concept → the exact FRED `series_id` (+ the transform to apply). Mirrors _resolve_fspattern:
    exact series_id → passthrough; else vector shortlist (/v1/ext/fred/find, full context: title+units+freq+SA+
    suggested_transform) → Jev pick (judged by `context`) + `__NONE__` → calibrated gate. Returns
    {status, query, series_id?, transform?, title?, confidence?, gate?, note?, candidates?}. The pick's
    suggested_transform rides along as the DEFAULT for fred_series (the client may still override)."""
    cands = _bget("/v1/ext/fred/find", {"q": q, "country": country, "limit": 15})
    cands = cands.get("candidates") or cands.get("series") or (cands if isinstance(cands, list) else [])
    if not cands:
        return {"status": "no_match", "query": q, "reason": "no candidate FRED series", "candidates": []}
    # FAST-PATH: the client already sent an exact FRED series_id → use it, skip Jev.
    exact = next((c for c in cands if str(c.get("series_id", "")).lower() == q.strip().lower()), None)
    if exact:
        return {"status": "resolved", "query": q, "series_id": exact["series_id"],
                "transform": exact.get("suggested_transform"), "title": exact.get("title"),
                "confidence": 1.0, "gate": "exact_key"}
    options, meta = {}, {}
    for c in cands:
        sid = c.get("series_id")
        if not sid:
            continue
        bits = [b for b in (c.get("title"), c.get("units"), c.get("frequency"),
                            c.get("seasonal_adjustment")) if b]
        desc = " · ".join(bits) or sid
        if c.get("suggested_transform"):
            desc += f" → transform {c['suggested_transform']}"
        if c.get("curated"):
            desc += " [curated]"
        options[sid] = desc
        meta[sid] = {"series_id": sid, "transform": c.get("suggested_transform"), "title": c.get("title")}
    options["__NONE__"] = _SERIES_NONE_OPT
    jev_q = (f'Resolve the entity "{q}" as it is used in the user\'s request: "{context.strip()}"'
             if context and context.strip() and context.strip().lower() != q.strip().lower() else q)
    r = _jev_pick(jev_q, _SERIES_RESOLVE_INSTR, options)
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": "not a FRED macro series (Jev: none fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"series_id": meta[k]["series_id"], "title": meta[k]["title"],
                  "transform": meta[k]["transform"], "prob": round(v, 3)} for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "series_id": pm.get("series_id"), "transform": pm.get("transform"),
               "title": pm.get("title"), "confidence": r.get("confidence"), "gate": gate}
        if gate == "soft":
            alts = ", ".join(c["series_id"] for c in top_cands[1:3])
            out["note"] = f"resolved '{q}' → {pm.get('series_id')} at lower confidence; alternatives: {alts}"
        return out
    reason = "two close FRED series — confirm which" if gate == "reconfirm" else "no confident FRED series match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

def _is_series_id(s: str) -> bool:
    """A cryptic FRED series_id already in hand → passthrough (skip resolve): an UPPERCASE single token that either
    carries a DIGIT (DGS10/T10YIE) or is long (≥6: CPIAUCSL/UNRATE/PCEPILFE). A short bare word ('GDP','CPI','PCE') is
    a CONCEPT → resolve (safer: 'CPI'→CPIAUCSL, not a broken passthrough)."""
    s = (s or "").strip()
    return bool(s) and " " not in s and s.isupper() and (any(ch.isdigit() for ch in s) or len(s) >= 6)

@mcp.tool(name="fred_series", title="Macro Series + Analysis (FRED)", annotations=_RO)
def fred_series(series_id: Annotated[str, _dq("A macro CONCEPT (any language — 'inflation', 'core PCE', 'unemployment "
                    "rate', '10y yield', 'อัตราว่างงาน') OR an exact FRED series_id you already hold (CPIAUCSL). The "
                    "SERVER resolves a concept → the canonical series + the RIGHT transform (no separate lookup). "
                    "🌐 a macro concept is safest in ENGLISH (a native concept may drift). 🔴 Pass the user's FULL "
                    "request in `context` so the server picks the right VARIANT (headline vs CORE CPI, SA vs NSA, PCE "
                    "vs CPI). ⛔ ONE concept per call — compare two = call twice + diff. For a NON-US concept put the "
                    "country in `country`, NOT in this field ('Japanese inflation' → series_id='inflation', country='JP').")],
                transform: Annotated[Optional[str], _d("FRED units transform — `lin` (level: a rate/ratio) · `pc1` (YoY %: inflation/price index) · "
                                                       "`pca` (annualized %: real GDP) · `pch` (period %) · `chg`/`ch1` (abs Δ). Omit → the resolved series' suggested transform.")] = None,
                from_: Annotated[Optional[str], _d("Start — ISO date or relative window `10y`/`5y`/`qtd` (dynamic, anchored to today).")] = None,
                to: Annotated[Optional[str], _d("End — ISO date. Omit → latest.")] = None,
                country: Annotated[Optional[str], _d("OPTIONAL ISO-2 to bias a CONCEPT to a country's series (JP, DE) — the nationality from the "
                                                     "question goes HERE, not in `series_id`. FRED intl coverage is uneven; omit for US (default).")] = None,
                context: Annotated[Optional[str], _d("OPTIONAL but RECOMMENDED — the user's FULL request VERBATIM (any language). Used to pick the "
                                                     "right series VARIANT (headline vs core, SA vs NSA). e.g. 'is US core inflation still sticky?'")] = None) -> dict:
    """"What is <macro indicator> / is it high vs history / how has it moved" — ONE FRED series, feature-extracted.
    Pass a macro CONCEPT (the server resolves it to the canonical series_id + the right transform) or an exact id.
    Returns `series` (transformed points) + an `analysis` block: `latest` (+date — always say as-of-when), `trend`,
    `change` (vs prior/YoY/window), `peak`/`trough`, and 🔑 `percentile`+`z_score` vs the window's own history (the
    money-shot for "high or low?" — e.g. unemployment 8th pct = historically very low), `volatility`, a one-line
    `read`. 🔵 `transform` matters and is auto-picked from the resolved series ("inflation" = pc1 YoY % of a price
    index, a rate = lin) — override only deliberately. QUOTE the `read`; narrate the percentile. Compare two = call
    once per concept and diff. A concept that isn't a FRED series (ISM/PMI, a commodity SPOT price → commodity_pulse)
    → honest no_match, not a fabrication. US-govt series are public domain (`_license_note`)."""
    _rs = None
    if not _is_series_id(series_id):                       # 🆕 collapse find_series: a CONCEPT → resolve server-side
        r = _resolve_series(series_id, country=country, context=context)
        if r["status"] != "resolved":
            return {"needs_confirmation": r["status"] == "reconfirm", "confirm": {series_id: {"kind": "series",
                        "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])}},
                    "_guide": "That isn't a unique FRED series — pick a `series_id` from candidates, or refine the "
                              "concept (core vs headline, SA vs NSA, PCE vs CPI) / add `context`, then re-call."}
        series_id = r["series_id"]
        if transform is None:
            transform = r.get("transform")               # carry the resolved series' suggested transform
        _rs = {"series_id": r["series_id"], "title": r.get("title"), "transform": r.get("transform"), "gate": r.get("gate")}
    res = _ext("/v1/ext/fred/series", {"series_id": series_id, "transform": transform, "from": from_, "to": to})
    if _rs and isinstance(res, dict):
        res["_resolved_series"] = _rs
    return res

# ── World Bank (Data360) — cross-country structural data (open, no key, cached) ───────────────────────
# There is NO find_indicator tool — wb_series resolves a structural concept (or an exact indicator id) server-side via
# _resolve_indicator (vector /v1/ext/wb/find → Jev pick → gate), carrying the right database + unit VARIANT. Annual
# structural data (consumption/GDP/demographics/poverty) — FRED's cross-country complement. Contract: docs/wb-api-for-mcp.md.
_INDICATOR_RESOLVE_INSTR = (
    "The state has `query`: a cross-country STRUCTURAL concept the user wants a World Bank indicator for (possibly the "
    "form 'Resolve the entity \"X\" as it is used in the user's request: \"<full request>\"' — resolve X using that "
    "CONTEXT). Each option is a candidate World Bank indicator: its name, unit hint, and database. Pick the SINGLE "
    "indicator + the right VARIANT the request MEANS. The variant is the code suffix / unit: `.ZS` = % of GDP or a "
    "SHARE (compare across country sizes) · `.CD` = current US$ (absolute size) · `.KD` = constant/REAL · `.KD.ZG` = "
    "% growth · `.PC`/`.PCAP` = PER CAPITA (living standards) · `.PP` = PPP. Read the request: 'as a share of GDP' → "
    ".ZS; 'in dollars / total size' → .CD; 'per person / per capita' → per-capita; 'in real terms' → .KD. Prefer a "
    "`curated` WB_WDI indicator when the request is generic. One option is `__NONE__` — choose it ONLY when the query "
    "is NOT a World Bank structural indicator at all.")
_INDICATOR_NONE_OPT = (
    "None of the candidates is the World Bank structural indicator the query means. ⚠️ LAST RESORT — pick this ONLY "
    "when the query is not World-Bank data at all: a single COMPANY / its stock or financials, a market/asset PRICE "
    "(a stock, a commodity spot, an FX rate), or gibberish. NOTE World Bank DOES carry ANNUAL versions of inflation, "
    "unemployment, interest rates etc. — so a genuine macro/structural concept must resolve to its candidate (never "
    "NONE); only a truly non-World-Bank thing is NONE.")

def _is_indicator_id(s: str) -> bool:
    """An exact World Bank indicator id already in hand → passthrough (skip resolve): a cryptic UPPERCASE code with an
    underscore (WB_WDI_NE_CON_PRVT_ZS). A plain concept ('household consumption', 'GDP per capita') → resolve."""
    s = (s or "").strip()
    return bool(s) and " " not in s and "_" in s and s.upper() == s

def _resolve_indicator(q: str, country: Optional[str] = None, context: Optional[str] = None) -> dict:
    """Resolve ONE structural concept → the exact World Bank indicator id (+ database). Mirrors _resolve_series:
    exact id → passthrough; else vector shortlist (/v1/ext/wb/find, full context: name+unit_hint+database) → Jev pick
    (judged by `context`) + `__NONE__` → calibrated gate. Returns {status, query, indicator?, database?, name?,
    confidence?, gate?, note?, candidates?}. The pick's `database` rides along as the default for wb_series."""
    cands = _bget("/v1/ext/wb/find", {"q": q, "country": country, "limit": 15})
    cands = cands.get("candidates") or cands.get("indicators") or (cands if isinstance(cands, list) else [])
    if not cands:
        return {"status": "no_match", "query": q, "reason": "no candidate World Bank indicators", "candidates": []}
    exact = next((c for c in cands if str(c.get("indicator", "")).lower() == q.strip().lower()), None)
    if exact:
        return {"status": "resolved", "query": q, "indicator": exact["indicator"], "database": exact.get("database"),
                "name": exact.get("name"), "confidence": 1.0, "gate": "exact_key"}
    options, meta = {}, {}
    for c in cands:
        ind = c.get("indicator")
        if not ind:
            continue
        desc = c.get("name") or ind
        if c.get("unit_hint"):
            desc += f" — {c['unit_hint']}"
        if c.get("database"):
            desc += f" (db {c['database']})"
        if c.get("curated"):
            desc += " [curated]"
        options[ind] = desc
        meta[ind] = {"indicator": ind, "database": c.get("database"), "name": c.get("name")}
    options["__NONE__"] = _INDICATOR_NONE_OPT
    jev_q = (f'Resolve the entity "{q}" as it is used in the user\'s request: "{context.strip()}"'
             if context and context.strip() and context.strip().lower() != q.strip().lower() else q)
    r = _jev_pick(jev_q, _INDICATOR_RESOLVE_INSTR, options)
    if r.get("pick") == "__NONE__":
        return {"status": "no_match", "query": q, "reason": "not a World Bank structural indicator (Jev: none fit)",
                "confidence": r.get("confidence"), "candidates": []}
    gate = _jev_gate(r)
    pm = meta.get(r.get("pick"), {})
    top_cands = [{"indicator": meta[k]["indicator"], "name": meta[k]["name"], "database": meta[k]["database"],
                  "prob": round(v, 3)} for k, v in r["probs"].items() if k in meta]
    if gate in ("resolve", "soft"):
        out = {"status": "resolved", "query": q, "indicator": pm.get("indicator"), "database": pm.get("database"),
               "name": pm.get("name"), "confidence": r.get("confidence"), "gate": gate}
        if gate == "soft":
            alts = ", ".join(c["indicator"] for c in top_cands[1:3])
            out["note"] = f"resolved '{q}' → {pm.get('indicator')} at lower confidence; alternatives: {alts}"
        return out
    reason = "two close World Bank indicators — confirm which" if gate == "reconfirm" else "no confident indicator match"
    return {"status": gate, "query": q, "reason": reason, "candidates": top_cands, "confidence": r.get("confidence")}

@mcp.tool(name="wb_series", title="World Bank Data + Analysis", annotations=_RO)
def wb_series(indicator: Annotated[str, _dq("A cross-country STRUCTURAL concept (any language — 'household consumption', "
                    "'GDP per capita', 'poverty rate', 'life expectancy', 'government debt', 'การบริโภค') OR an exact World "
                    "Bank indicator id you already hold (WB_WDI_NE_CON_PRVT_ZS). The SERVER resolves a concept → the "
                    "canonical indicator + the right unit VARIANT (no separate lookup). 🔴 Pass the user's FULL request in "
                    "`context` so the server picks the VARIANT: % of GDP/share (compare across country sizes) vs current "
                    "US$ (absolute) vs per-capita (living standards) vs constant/real. World Bank = ANNUAL structural data "
                    "(consumption/GDP/demographics/poverty) — NOT high-frequency macro (CPI/unemployment/rates → fred_series).")],
              country: Annotated[str, _d("Country as ISO3 or a name (`Thailand`/`THA`); COMMA-SEP for a cross-country compare "
                                         "(`THA,JPN,USA`); or an aggregate (`WLD` world · `EMU` euro area · `HIC`/`MIC`/`LIC` income groups).")],
              from_: Annotated[Optional[int], _d("Start year (default ≈ last 15y, dynamic).")] = None,
              to: Annotated[Optional[int], _d("End year (default latest).")] = None,
              context: Annotated[Optional[str], _d("OPTIONAL but RECOMMENDED — the user's FULL request VERBATIM (any language). Used to pick the "
                                                   "right unit VARIANT (% of GDP vs US$ vs per-capita vs real). e.g. 'compare household spending as a share of GDP'.")] = None,
              database: Annotated[Optional[str], _d("ADVANCED — the indicator's source database (WB_WDI, IMF_FSIC). Auto-derived from the resolved concept; override only for a non-WDI id you pass directly.")] = None) -> dict:
    """"<structural indicator> for <country>, over time / vs other countries" — World Bank annual data,
    feature-extracted (open data, 3 credits). Pass a structural CONCEPT (the server resolves it to the canonical
    indicator + variant) or an exact indicator id. Returns `results:[{country, series:[{year,value}], analysis}]`
    (one per country); `analysis` = `latest`(+year), `trend`, `cagr_pct`, `change`, `peak`/`trough`. ⭐ For a
    MULTI-COUNTRY call (comma-sep `country`) a top-level `ranking` orders them by the latest value — the
    cross-country compare FRED can't do. Annual STRUCTURAL data → read levels + CAGR, not high-frequency moves.
    A country/year with no data is omitted (never interpolated). The right VARIANT (%GDP vs US$ vs per-capita) is
    picked from your `context`. A concept that isn't World-Bank structural (CPI/unemployment → fred_series) → honest
    no_match. Surface `_license_note` when showing data."""
    _ri = None
    if not _is_indicator_id(indicator):                    # 🆕 collapse find_indicator: a CONCEPT → resolve server-side
        r = _resolve_indicator(indicator, country=country, context=context)
        if r["status"] != "resolved":
            return {"needs_confirmation": r["status"] == "reconfirm", "confirm": {indicator: {"kind": "indicator",
                        "status": r["status"], "reason": r.get("reason"), "candidates": r.get("candidates", [])}},
                    "_guide": "That isn't a unique World Bank indicator — pick one from candidates, or refine the "
                              "concept/variant (% of GDP vs US$ vs per-capita) / add `context`, then re-call."}
        indicator = r["indicator"]
        if database is None:
            database = r.get("database")                   # carry the resolved indicator's database
        _ri = {"indicator": r["indicator"], "name": r.get("name"), "database": r.get("database"), "gate": r.get("gate")}
    res = _ext("/v1/ext/wb/series", {"indicator": indicator, "country": country, "from": from_, "to": to, "database": database})
    if _ri and isinstance(res, dict):
        res["_resolved_indicator"] = _ri
    return res

# curated dashboards — the economist mental-model (which indicators make each read); series confirmed via
# fred_series 2026-08-04. Each = (series_id, transform, label).
_MACRO_DASH = {
    "economy": [("GDPC1", "pca", "real GDP growth"), ("INDPRO", "pc1", "industrial production"),
                ("CPIAUCSL", "pc1", "CPI inflation"), ("PCEPILFE", "pc1", "core PCE"),
                ("UNRATE", "lin", "unemployment"), ("PAYEMS", "chg", "nonfarm payrolls"),
                ("FEDFUNDS", "lin", "fed funds (policy)")],
    "inflation": [("CPIAUCSL", "pc1", "headline CPI"), ("CPILFESL", "pc1", "core CPI"),
                  ("PCEPILFE", "pc1", "core PCE"), ("PPIACO", "pc1", "producer prices"),
                  ("T5YIE", "lin", "5y inflation expectations")],
    "labor": [("PAYEMS", "chg", "nonfarm payrolls"), ("UNRATE", "lin", "unemployment"),
              ("CIVPART", "lin", "participation"), ("CES0500000003", "pc1", "avg hourly earnings"),
              ("ICSA", "lin", "initial jobless claims"), ("JTSJOL", "lin", "job openings (JOLTS)")],
    "consumer": [("RSAFS", "pc1", "retail sales"), ("DSPIC96", "pc1", "real disposable income"),
                 ("UMCSENT", "lin", "consumer sentiment"), ("PSAVERT", "lin", "personal saving rate"),
                 ("TOTALSL", "pc1", "consumer credit")],
    "housing": [("HOUST", "lin", "housing starts"), ("PERMIT", "lin", "building permits"),
                ("CSUSHPINSA", "pc1", "home prices"), ("EXHOSLUSM495S", "lin", "existing home sales"),
                ("MORTGAGE30US", "lin", "30y mortgage rate")],
    "recession-risk": [("T10Y2Y", "lin", "2s10s yield curve"), ("SAHMREALTIME", "lin", "Sahm-rule trigger"),
                       ("ICSA", "lin", "initial jobless claims"), ("CFNAI", "lin", "Chicago Fed activity index"),
                       ("RECPROUSM156N", "lin", "recession probability")],
}
_MACRO_ALIASES = {"regime": "economy", "gdp": "economy", "growth": "economy", "us economy": "economy",
                  "macro": "economy", "jobs": "labor", "employment": "labor", "unemployment": "labor",
                  "prices": "inflation", "cpi": "inflation", "recession": "recession-risk",
                  "recession risk": "recession-risk", "housing market": "housing", "real estate": "housing"}

def _fred_slim(cli, sid: str, tf: str, label: str, frm: str = "10y") -> dict:
    """One FRED series → slim feature-extract for a dashboard (latest + percentile + trend + read).
    ⚠️ Takes `cli` (the MarketDX client) explicitly — callers run this in ThreadPoolExecutor workers, and the
    per-request auth key lives in a contextvar that does NOT propagate into worker threads. Resolve `cli` via
    mdx() in the MAIN thread and pass it in (same pattern the other composites use)."""
    try:
        d = cli._get("/v1/ext/fred/series", {"series_id": sid, "transform": tf, "from": frm}).data
        a = d.get("analysis") or {}
        return {"indicator": label, "series_id": sid, "transform": tf,
                "title": (d.get("meta") or {}).get("title"), "latest": a.get("latest"),
                "trend": a.get("trend"), "percentile": a.get("percentile"),
                "z_score": a.get("z_score"), "read": a.get("read")}
    except Exception as e:
        return {"indicator": label, "series_id": sid, "error": str(e)[:80]}

@mcp.tool(title="Macro Pulse (FRED)", annotations=_RO)
def macro_pulse(scope: Annotated[str, _d("A macro DASHBOARD: `economy` (overall regime) · `inflation` · `labor` · `consumer` · "
                                         "`housing` · `recession-risk`. For ONE indicator use fred_series (pass a concept); for the "
                                         "rates/yield-curve use bond_pulse.")],
                window: Annotated[Optional[str], _d("History window for each indicator's percentile/trend (default `10y`; e.g. `5y`/`20y`).")] = None,
                country: Annotated[Optional[str], _d("OPTIONAL ISO-2 — v0 dashboards are US; non-US returns a note (use fred_series(q=<concept>, country=XX) per indicator).")] = None) -> dict:
    """⭐ "How is <the economy / consumer / labor market / housing / inflation> doing? / recession risk / soft-
    landing or stagflation?" — the MACRO REGIME & DASHBOARD read. Fuses the key indicators for a SCOPE, each
    feature-extracted (latest + where it sits vs its OWN history = `percentile` + trend), so you SYNTHESIZE the
    regime instead of fetching one series at a time. Scopes: `economy` (growth×inflation×labor×policy → the
    regime) · `inflation` · `labor` · `consumer` · `housing` · `recession-risk`.
      • SYNTHESIZE, don't dump: lead with the growth×inflation quadrant (reflation growth↑infl↑ / goldilocks
        growth↑infl↓ / stagflation growth↓infl↑ / slowdown growth↓infl↓), modulated by labor tightness (low
        unemployment-percentile + high openings = tight) and policy (fed funds vs inflation). `percentile` is the
        money-shot — "unemployment 8th pct of its history = historically very low". State each as-of date.
      • Voice: the regime + the MECHANISM it implies (e.g. rising real yields historically pressure gold / long-
        duration) — NOT advice or a forecast; hand judgment back; if the user holds names, tie the regime to them.
      • Boundaries: no ISM/PMI on FRED; commodity SPOT → commodity_pulse; rates/curve detail → bond_pulse;
        external/trade → the Comtrade tools. A component with `error` = that series wasn't available; say so.
    For ONE indicator → fred_series (pass a concept); THIS is the multi-indicator regime composite."""
    key = _MACRO_ALIASES.get(scope.strip().lower(), scope.strip().lower())
    dash = _MACRO_DASH.get(key)
    if not dash:
        return {"error": f"unknown scope '{scope}'. Use one of: {', '.join(_MACRO_DASH)} "
                         f"(or fred_series with a concept for a single indicator)."}
    if country and country.strip().upper() not in ("US", "USA", "UNITED STATES"):
        return {"scope": key, "note": f"macro_pulse dashboards are US-only in v0; for {country} query each "
                "indicator via fred_series(q=<concept>, country=…) (FRED intl coverage is uneven)."}
    frm = window or "10y"
    cli = mdx()   # resolve in the MAIN thread — the auth contextvar doesn't cross into worker threads
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(dash))) as ex:
        rows = list(ex.map(lambda t: _fred_slim(cli, t[0], t[1], t[2], frm), dash))
    return {
        "scope": key, "window": frm, "country": "US", "indicators": rows,
        "_guide": ("SYNTHESIZE a regime read, don't list. For `economy`/`recession-risk`: place it on the "
                   "growth×inflation quadrant (reflation/goldilocks/stagflation/slowdown), then modulate with "
                   "labor tightness (low `unemployment` percentile + high openings) and policy stance (fed funds "
                   "vs inflation). LEAD with each indicator's `percentile` — where it sits vs its OWN history is "
                   "the answer to 'high or low' (a bare level isn't). Quote each `read` + its as-of date. Then "
                   "the MECHANISM/implication (facts, not advice; hand judgment back; tie to the user's holdings "
                   "if any). Route out where relevant: rates/curve → bond_pulse, commodity spot → commodity_pulse, "
                   "trade/external → the Comtrade tools. Any indicator with `error` = unavailable, say so."),
        "_license_note": "Macro data via FRED; US-government series are public domain.",
    }

@mcp.tool(title="Suggest Explorations", annotations=_RO)
def suggest_cta(theme: Annotated[str, _d("A theme/scope to suggest a next-step call-to-action for.")],
                window: Annotated[str, _d(_WINDOW)] = "30d") -> dict:
    """After answering, propose 1-2 data-backed 'explore further' hooks that pull the user into the
    graph's moat (ripple/relations/commodity/off-coverage). Server-side: theme_summary(has ripple/
    entities/aspects) + a semantic news search, then deepseek curates ONLY data-backed hooks.
    Validated in /tmp/mcp-gate/cta_tool.js (there via direct probes; here via the summary composite)."""
    node, err = _theme_node(theme)
    if err: return err
    brief = mdx().theme(node).summary(window=window)  # already carries winners/losers/top_entities/aspect_heatmap/ripple
    signals = {k: brief.get(k) for k in ("winners", "losers", "top_entities", "top_assets",
                                         "aspect_heatmap", "ripple", "pulse")}
    curate = ("Given a theme brief's REAL signals, write 1-2 CTAs inviting deeper exploration. "
              "STRICT: use ONLY item names/numbers present in the signals; never invent. Prefer the "
              "highest-moat, most-active thread (ripple/relations over generic). Cite the number. "
              'Return JSON: {"ctas":[{"door":"...","hook":"<one line>"}]}')
    return _deepseek(curate, json.dumps(signals, ensure_ascii=False), temperature=0.4)

# ── RESOURCES (injected into the client LLM's context) ───────────────────────
@mcp.resource("marketdx://policy")
def gate_policy() -> str:
    """The gate & framing policy (skill.md) the client LLM should follow — scope resolution, the 5
    response stances, honest fidelity, no-fudge. Kept alongside the server."""
    p = _HERE / "policy.md"
    return p.read_text() if p.exists() else "policy.md not found"

@mcp.resource("marketdx://capabilities")
def capabilities() -> str:
    """Live coverage/capabilities map: covered markets + depth, asset classes, news window, tier-1
    themes — so the client scopes correctly (expand 'Asia'→covered set; don't request uncovered)."""
    try:
        return json.dumps({"enums": mdx().enums(), "account": mdx().account()}, ensure_ascii=False)
    except Exception as e:  # keep the resource readable even if the API hiccups
        return json.dumps({"error": str(e)})

# ── OAuth (WorkOS AuthKit) — MCP Authorization ────────────────────────────────
# When WORKOS_ISSUER is set the server advertises itself as an OAuth 2.0 Protected Resource (RFC 9728):
# an unauthenticated MCP request gets 401 + WWW-Authenticate pointing at the metadata document.
#
# We act as an **authorization-server-metadata proxy**: `authorization_servers` names US, and we serve
# BOTH RFC 8414 (`oauth-authorization-server`) and OIDC (`openid-configuration`) discovery docs from our
# own origin, built from WorkOS's RFC 8414 doc with `issuer` rewritten to us. Why: WorkOS advertises
# `registration_endpoint` + `client_id_metadata_document_supported` ONLY in its RFC 8414 doc, NOT in its
# openid-configuration — so a client that reads the OIDC doc (as Claude did → "automatic client
# registration isn't supported") sees no DCR/CIMD. Proxying both docs guarantees the client finds them
# either way and can use CIMD (no registration) or DCR. The OAuth endpoints still point at WorkOS, which
# authenticates the user (via our External Sign-in URI) and mints the JWT; we just forward the Bearer.
# Unset → no OAuth advertised; only the Bearer-key path works.
_WORKOS_ISSUER = os.environ.get("WORKOS_ISSUER", "").rstrip("/") or None
_RESOURCE_WK = "/.well-known/oauth-protected-resource"
_AS_WK = ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")
_AS_CACHE: dict = {}   # WorkOS RFC 8414 metadata, fetched once

def _origin(scope) -> str:
    hdrs = dict(scope.get("headers") or {})
    host = hdrs.get(b"host", b"").decode() or "mcp.marketdx.lab.ai"
    proto = hdrs.get(b"x-forwarded-proto", b"https").decode().split(",")[0].strip() or "https"
    return f"{proto}://{host}"

def _resource_metadata(scope) -> dict:
    origin = _origin(scope)
    # `resource` must equal the token audience the client requests — our MCP endpoint URL. Derived
    # from the request host so both mcp.marketdx.lab.ai and the run.app URL self-describe correctly.
    return {
        "resource": os.environ.get("MCP_RESOURCE_URL") or f"{origin}/mcp",
        "authorization_servers": [origin],   # we proxy the AS metadata (see block comment)
        "bearer_methods_supported": ["header"],
        # offline_access is REQUIRED so the client asks WorkOS for a refresh token and can renew the
        # access token silently — without it a spec-compliant client (Claude) never requests refresh
        # and must reconnect every time the ~1h access token expires. WorkOS supports it.
        "scopes_supported": ["openid", "email", "profile", "offline_access"],
    }

async def _as_metadata(scope) -> dict:
    """WorkOS RFC 8414 metadata with `issuer` rewritten to our origin (RFC 8414 §3.3 self-consistency).
    Endpoints still point at WorkOS. Fetched once and cached; falls back to a minimal doc on failure."""
    import asyncio, urllib.request
    if not _AS_CACHE:
        def _fetch():
            url = f"{_WORKOS_ISSUER}/.well-known/oauth-authorization-server"
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read())
        try:
            _AS_CACHE.update(await asyncio.to_thread(_fetch))
        except Exception:  # WorkOS unreachable → minimal doc from known endpoints. Return WITHOUT
            fallback = {   # caching so a transient boot-time egress hiccup doesn't poison the cache
                "authorization_endpoint": f"{_origin(scope)}/oauth2/authorize",  # our force-offline_access proxy
                "token_endpoint": f"{_WORKOS_ISSUER}/oauth2/token",
                "registration_endpoint": f"{_WORKOS_ISSUER}/oauth2/register",
                "jwks_uri": f"{_WORKOS_ISSUER}/oauth2/jwks",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "scopes_supported": ["openid", "email", "profile", "offline_access"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "client_id_metadata_document_supported": True,
                "issuer": _origin(scope),
            }
            return fallback
    meta = dict(_AS_CACHE)
    meta["issuer"] = _origin(scope)   # served from our origin → issuer must be us
    # Guarantee offline_access is advertised (don't depend on WorkOS's list) so the client requests a
    # refresh token → silent renewal instead of reconnect-on-expiry.
    meta["scopes_supported"] = sorted(set(meta.get("scopes_supported") or []) |
                                      {"openid", "email", "profile", "offline_access"})
    # Point authorize at OUR proxy (below) which force-injects offline_access before forwarding to
    # WorkOS — advertising the scope isn't enough (a client, e.g. Claude, may not copy scopes_supported
    # into its authorize request → WorkOS issues no refresh token → hourly reconnect). token/jwks/
    # register still point at WorkOS (unchanged).
    meta["authorization_endpoint"] = f"{_origin(scope)}/oauth2/authorize"
    return meta

async def _send_json(send, status: int, obj: dict, extra_headers: list | None = None):
    body = json.dumps(obj).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += extra_headers or []
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})

class _AuthASGI:
    """Pure-ASGI middleware (NOT BaseHTTPMiddleware — that runs the route in a separate task where a
    contextvar set here wouldn't propagate). Reads `Authorization: Bearer <key>` and stashes it in
    _req_key for the duration of the request, so mdx() picks up THIS caller's key. Also implements the
    OAuth protected-resource discovery (RFC 9728) when WORKOS_ISSUER is configured."""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        auth = dict(scope.get("headers") or {}).get(b"authorization", b"").decode()
        key = auth[7:].strip() if auth[:7].lower() == "bearer " else None

        # Public branding asset (no auth) — the connector's icon.
        if path == "/favicon.ico":
            hdrs = [(b"content-type", b"image/x-icon"), (b"content-length", str(len(_FAVICON)).encode()),
                    (b"cache-control", b"public, max-age=86400")]
            await send({"type": "http.response.start", "status": 200 if _FAVICON else 404, "headers": hdrs})
            await send({"type": "http.response.body", "body": _FAVICON})
            return

        if _WORKOS_ISSUER:
            # Authorize proxy — force-inject offline_access so WorkOS always mints a refresh token,
            # then 302 to WorkOS's real authorize. Advertising offline_access in scopes_supported is not
            # enough: a client (e.g. Claude, whose CIMD declares no scope) may not copy it into its
            # authorize request → no refresh token → the user must reconnect every ~1h. Injecting it here
            # is client-independent. PKCE (code_challenge) is passed through untouched; the token exchange
            # still hits WorkOS directly, so the verifier check is unaffected.
            if path == "/oauth2/authorize":
                from urllib.parse import parse_qsl, urlencode
                params = dict(parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True))
                scopes = (params.get("scope") or "").split()
                for s in ("openid", "offline_access"):
                    if s not in scopes:
                        scopes.append(s)
                params["scope"] = " ".join(scopes)
                target = f"{_WORKOS_ISSUER}/oauth2/authorize?{urlencode(params)}"
                await send({"type": "http.response.start", "status": 302,
                            "headers": [(b"location", target.encode()), (b"content-length", b"0")]})
                await send({"type": "http.response.body", "body": b""})
                return
            # Public discovery documents (RFC 9728 + RFC 8414/OIDC proxy) — no auth.
            if path.startswith(_RESOURCE_WK):
                return await _send_json(send, 200, _resource_metadata(scope))
            if path.startswith(_AS_WK):
                return await _send_json(send, 200, await _as_metadata(scope))
            # Unauthenticated MCP call → challenge so the client starts the OAuth flow. (Bearer present
            # → fall through; the token, key or JWT, is validated downstream by the API.)
            if key is None:
                challenge = f'Bearer resource_metadata="{_origin(scope)}{_RESOURCE_WK}"'
                return await _send_json(send, 401, {"error": "unauthorized"},
                                        [(b"www-authenticate", challenge.encode())])

        tok = _req_key.set(key)
        try:
            await self.app(scope, receive, send)
        finally:
            _req_key.reset(tok)

def main() -> None:
    """Console entry point (`marketdx-mcp`). MCP_TRANSPORT=http → hosted Streamable HTTP (per-request
    Bearer auth); else stdio (local, MARKETDX_API_KEY env)."""
    if os.environ.get("MCP_TRANSPORT", "stdio").replace("-", "") in ("http", "streamablehttp"):
        import uvicorn
        app = _AuthASGI(mcp.streamable_http_app())
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        mcp.run()   # stdio

if __name__ == "__main__":
    main()
