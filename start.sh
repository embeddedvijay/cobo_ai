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
PID_FILE="$ROOT_DIR/.cobo-service.pids"

# A previous Electron window can be force-closed before its children notice.
# Clean only PIDs whose current directory is this exact Cobo project; never
# use broad `pkill node` / `pkill uvicorn`, which could stop Boss/Nikku.
stop_stale_cobo_processes() {
  [[ -f "$PID_FILE" ]] || return 0
  while IFS= read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" == "$ROOT_DIR" ]] || continue
    kill -TERM "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  sleep 1
}

stop_stale_cobo_processes

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${NODE_PID:-}" ]] && kill "$NODE_PID" 2>/dev/null || true
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
}
trap cleanup INT TERM EXIT

"$PYTHON_BIN" -m uvicorn backend.app.main:app --host "${BACKEND_HOST:-127.0.0.1}" --port "$BACKEND_PORT" --no-access-log &
BACKEND_PID=$!

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null
node "$ROOT_DIR/src/index.mjs" &
NODE_PID=$!
printf '%s\n%s\n' "$BACKEND_PID" "$NODE_PID" > "$PID_FILE"
wait "$NODE_PID"
