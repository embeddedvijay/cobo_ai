#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Electron supplies a generated desktop runtime configuration. Preserve it
# across `.env` loading, otherwise an old COBO_RUNTIME_CONFIG_PATH in .env
# silently makes the service start with config.yaml instead of the customer's
# current Input Group rules.
DESKTOP_RUNTIME_CONFIG="${COBO_RUNTIME_CONFIG_PATH:-}"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
if [[ -n "$DESKTOP_RUNTIME_CONFIG" ]]; then
  export COBO_RUNTIME_CONFIG_PATH="$DESKTOP_RUNTIME_CONFIG"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKEND_PORT="${BACKEND_PORT:-8015}"

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

"$PYTHON_BIN" -m uvicorn backend.app.main:app --host "${BACKEND_HOST:-127.0.0.1}" --port "$BACKEND_PORT" --no-access-log &
BACKEND_PID=$!

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null
node src/index.mjs
