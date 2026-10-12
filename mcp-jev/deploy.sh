#!/usr/bin/env bash
# Deploy the Ava Advisor MCP server to Cloud Run (us-east1) — hosted Streamable HTTP.
# Usage:  ./deploy.sh
# Env:    PROJECT (default ava-advisor-26c7b)  REGION (default us-east1)
#
# Runtime secrets: DEEPSEEK_API_KEY (composite tools) + TYPESAFE_API_KEY (Jev resolver — REQUIRED, every
# collapsed find_* resolver calls Jev; without it concept/NL inputs error "no TYPESAFE_API_KEY set"). NO
# Ava Advisor key — auth is per-request
# (the caller's Bearer). After first deploy, map the domain ONCE:
#   gcloud beta run domain-mappings create --service marketdx-mcp \
#     --domain mcp.ava.fund --region us-east1 --project ava-advisor-26c7b
#   → then add the CNAME/A records it prints to the ava.fund DNS zone.
# (The Cloud Run service keeps its internal name `marketdx-mcp`; the legacy mcp.marketdx.app mapping
#  stays in place so existing connectors keep working.)
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
  --set-secrets "DEEPSEEK_API_KEY=DEEPSEEK_API_KEY:latest,TYPESAFE_API_KEY=TYPESAFE_API_KEY:latest" \
  --update-env-vars "WORKOS_ISSUER=${WORKOS_ISSUER:-https://select-horse-71.authkit.app}" \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 4 --timeout 120

echo "Deployed. Test the .run.app URL, then map mcp.ava.fund (see header)."
