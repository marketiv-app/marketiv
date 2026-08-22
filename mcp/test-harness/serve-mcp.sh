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

# free the port if a stale server is holding it
lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -r kill 2>/dev/null || true

echo "serve-mcp: port=$PORT backend=$BASE  (python 3.12, mcp<2)  log=$LOG"
exec env MCP_TRANSPORT=http PORT="$PORT" MARKETDX_BASE_URL="$BASE" \
  uv run --no-project --python 3.12 --with 'mcp<2',marketdx,openai,uvicorn \
  python "$SRV"
