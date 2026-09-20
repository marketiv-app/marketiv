#!/usr/bin/env bash
# ⛔⛔ RETIRED 2026-09-20 — DO NOT RUN. This is the OLD pre-collapse MCP server (still has 19 find_* tools
#     and mounts NO TYPESAFE_API_KEY). Prod `marketdx-mcp` is now served from ../mcp-jev (find_* collapsed +
#     DELETED, Jev resolution server-side, rev 00169+). Running THIS deploy.sh would OVERWRITE prod with the
#     old find_* server AND break the Jev resolver — a full rollback of the resolver-collapse work.
#     → Deploy from ../mcp-jev/deploy.sh instead. See Ava-Advisor docs/architecture/mcp-resolver-collapse.md.
echo "⛔ RETIRED: this old (find_*) MCP server must NOT be deployed — use ../mcp-jev/deploy.sh instead." >&2
echo "   (running it would roll prod back to the find_* version and drop TYPESAFE_API_KEY)." >&2
exit 1
# ---- original script below (dead; kept for reference only) ----
# Deploy the MarketDX MCP server to Cloud Run (us-east1) — hosted Streamable HTTP.
# Usage:  ./deploy.sh
# Env:    PROJECT (default ava-advisor-26c7b)  REGION (default us-east1)
#
# One runtime secret: DEEPSEEK_API_KEY (composite tools). NO MarketDX key — auth is per-request
# (the caller's Bearer). After first deploy, map the domain ONCE:
#   gcloud beta run domain-mappings create --service marketdx-mcp \
#     --domain mcp.marketdx.lab.ai --region us-east1 --project ava-advisor-26c7b
#   → then add the CNAME/A records it prints to the marketdx.lab.ai DNS zone.
set -euo pipefail
PROJECT="${PROJECT:-ava-advisor-26c7b}"
REGION="${REGION:-us-east1}"
SERVICE="marketdx-mcp"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Deploying ${SERVICE} → Cloud Run (${PROJECT}/${REGION})"
gcloud run deploy "${SERVICE}" \
  --source "${HERE}" \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-secrets "DEEPSEEK_API_KEY=DEEPSEEK_API_KEY:latest" \
  --update-env-vars "WORKOS_ISSUER=${WORKOS_ISSUER:-https://select-horse-71.authkit.app}" \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 4 --timeout 120

echo "Deployed. Test the .run.app URL, then map mcp.marketdx.lab.ai (see header)."
