#!/bin/bash
# Strong, PINNED MCP test-server launcher — the ONLY supported way to bring up server.py for a dumb-client test.
# No more ad-hoc "change python / which mcp version" fiddling: everything is pinned here.
#   - python 3.12 (mcp 2.x on 3.14 ships a broken wheel; 3.12 is the known-good line)
#   - mcp<2      (mcp 2.0 REMOVED mcp.server.fastmcp, which server.py imports)
# Usage:  ./serve-mcp.sh                 # → http on :8901, backend = deployed prod
#         BASE=http://127.0.0.1:8095 ./serve-mcp.sh   # point at a LOCAL news-api
#         PORT=8902 ./serve-mcp.sh
# Logs → /tmp/mcp_<port>.log ; run in the background with `&`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRV="$(cd "$HERE/.." && pwd)/server.py"
PORT="${PORT:-8901}"
BASE="${BASE:-https://news-api-sgrtkib7zq-ue.a.run.app}"   # deployed news-api (prod) by default
LOG="/tmp/mcp_${PORT}.log"

# Keys live in the local mcp-jev/.env (TYPESAFE_API_KEY for the unified Jev concept resolver; server.py reads them
# from the process env and does NOT auto-load dotenv). Source it so a fresh shell has them. (NOT Secret Manager —
# the Jev key is local-only; a sandbox gcloud call returns empty.)
ENVF="$(cd "$HERE/.." && pwd)/.env"
if [ -f "$ENVF" ]; then set -a; . "$ENVF"; set +a; fi
[ -n "${TYPESAFE_API_KEY:-}" ] && echo "serve-mcp: TYPESAFE_API_KEY loaded (Jev concept resolver enabled)" || echo "serve-mcp: WARN no TYPESAFE_API_KEY — the concept resolver will error"

# free the port if a stale server is holding it
lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -r kill 2>/dev/null || true

echo "serve-mcp: port=$PORT backend=$BASE  (python 3.12, mcp<2)  log=$LOG"
exec env MCP_TRANSPORT=http PORT="$PORT" MARKETDX_BASE_URL="$BASE" TYPESAFE_API_KEY="${TYPESAFE_API_KEY:-}" DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}" \
  uv run --no-project --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn \
  python "$SRV"
