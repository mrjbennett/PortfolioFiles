#!/usr/bin/env bash
# Start the app, run the Postman collection with Newman, stop the app.
# Usage: scripts/newman.sh [rc3|fixed]     (default: rc3)
set -euo pipefail
cd "$(dirname "$0")/.."

BUILD="${1:-rc3}"
PORT="${PORT:-5055}"
DB="$(mktemp -d)/billing.db"
mkdir -p results

BILLING_BUILD="$BUILD" BILLING_DB="$DB" PORT="$PORT" python3 -m app.server >/dev/null 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 0.5
done

npx --yes newman run postman/billing-api.postman_collection.json \
  --environment postman/local.postman_environment.json \
  --env-var "baseUrl=http://127.0.0.1:$PORT" \
  --reporters cli,junit \
  --reporter-junit-export "results/newman-$BUILD.xml"
