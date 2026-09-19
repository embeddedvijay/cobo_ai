#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
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
