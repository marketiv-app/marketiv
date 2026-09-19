# run13 — UNIFIED concept resolver (kills find_gics + find_megatrend + deepseek/gazetteer)

**T1 attest:** re-read RESOLVER-TEST-GUIDE.md (blind client writes own args; grade process+output from REAL returned
data, never self-report; mechanical tools/list). Server = :8902 → local :8090 DEBUG (judge CORRECTNESS not latency),
Jev key from mcp-jev/.env.

## Verdict: gate [A] PASS — 10/10 blind cases
- **0 calls** to find_gics / find_megatrend (both DELETED → absent from tools/list → a blind client literally cannot
  round-trip through them). **0 resolver round-trips**: every concept resolved server-side and the tool EXECUTED in
  one shot. The single reconfirm (A-q5) is the DESIGNED honest `not_a_sector` gate, not a find_* bounce.
- **Axis all correct:** semiconductors / AI / electric-vehicles → THEME; banks / retail / insurance / healthcare → GICS.
- **Multi-home proven END-TO-END from real member lists** (not just the resolver): `retail` → Walmart/Costco/Kroger
  (staples retail 301010) + Amazon/Target (discretionary 2550); `banks,insurance` → 4010,40203010,4030,35102030.
- **C11 single-axis honesty:** the gics-only `screen_dividends` refused a THEME concept ('semiconductors') with an
  actionable guide instead of fabricating a scope.
- **Boundary:** a blind client treated "my favorite stocks" as not-an-industry and never fabricated a screen.

## Per case
| id | question | tool (client's own choice) | axis | result |
|----|----------|----------------------------|------|--------|
| A-q1 | semiconductor stocks doing? | theme_pulse(q=semiconductors) | theme | real pulse ✅ |
| A-q2 | bank stocks | screen_stocks(gics=banks) | gics 4010(+40203010) | banks ✅ |
| A-q3 | AI companies most talked about | screen_stocks(gics='artificial intelligence') | theme 10000000 | NVDA/Alphabet ✅ |
| A-q4 | retail companies | screen_stocks(gics=retail) | gics 2550+301010 | Walmart/Costco/Amazon ✅ multi-home |
| A-q5 | high-dividend semiconductors | screen_dividends(gics=semiconductors)→reconfirm→GICS code | honest gate | C11 ✅ |
| B-q1 | banks AND insurance together | screen_stocks(gics='banks,insurance') | gics 4010/40203010/4030/35102030 | compound+multi-home ✅ |
| B-q2 | EV theme performing? | theme_pulse(q='electric vehicles') | theme | EV pulse ✅ |
| B-q3 | cybersecurity players | theme_players(theme=cybersecurity) | theme | 214 members ✅ |
| B-q4 | my favorite stocks | list_playlists | — | boundary respected ✅ |
| B-q5 | healthcare reliable dividend | screen_dividends(gics=healthcare) | gics 35 | 166 payers ✅ |

## Minor / non-blocking
- UX asymmetry: `screen_stocks`/`screen_unified` accept a theme WORD in `gics` (route it to the theme leg), but the
  gics-only `screen_dividends` refuses it (honest, by design). Consistent-but-asymmetric; acceptable.
- "banks" pulls in asset-management (40203010) and mega-caps outrank pure-plays in theme rosters — expected
  taxonomy/ranking behavior, not resolver defects.

## Diff vs run12 (gics-only collapse)
run12 collapsed find_gics via the deepseek/gazetteer `_resolve_gics_codes`. run13 REPLACES that entirely: find_gics
AND find_megatrend are gone; ALL 11 consumers resolve through the unified vector+Jev `_resolve_concept`; the whole
deepseek/gazetteer resolver is deleted (deepseek remains only for the ETF-pick + CTA-curation content features).
