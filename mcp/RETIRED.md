# ⛔ RETIRED — old pre-collapse MCP server

**Date:** 2026-09-20

This directory is the **OLD** MarketDX MCP server (still exposes 19 `find_*` resolver tools). It has been
**superseded** by [`../mcp-jev/`](../mcp-jev), which is what serves prod `marketdx-mcp` (Cloud Run us-east1,
rev 00169+): every `find_*` was collapsed into its consumer + deleted, and resolution now happens
server-side (vector + Jev).

- **Do NOT deploy from here.** `deploy.sh` is guarded (`exit 1`) — it targets the SAME live service, so a run
  would roll prod back to the `find_*` version and drop `TYPESAFE_API_KEY`.
- **Deploy from** `../mcp-jev/deploy.sh`.
- Kept for reference only (resolver-replacement PoC lineage). Safe to delete later.

Overview + how-to-call: `Ava Advisor/docs/architecture/mcp-resolver-collapse.md`.
