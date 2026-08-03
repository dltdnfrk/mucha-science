#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WEB_PORT=5173

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "uv is required. Install it, then run this script again." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  printf '%s\n' "npm is required. Install Node.js, then run this script again." >&2
  exit 1
fi

pipeline_port="$(
  python3 -c '
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_:
    socket_.bind(("127.0.0.1", 0))
    print(socket_.getsockname()[1])
'
)"

cleanup() {
  if kill -0 "$pipeline_pid" 2>/dev/null; then
    kill "$pipeline_pid"
    wait "$pipeline_pid" 2>/dev/null || true
  fi
}

(
  cd "$ROOT"
  PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    uv run python -m src.muchanipo.web.websocket_server \
      --host 127.0.0.1 \
      --port "$pipeline_port"
) &
pipeline_pid=$!
trap cleanup EXIT INT TERM

printf '%s\n' "Mucha Science local web app: http://127.0.0.1:${WEB_PORT}"
printf '%s\n' "Pipeline WebSocket: ws://127.0.0.1:${pipeline_port}/api/pipeline"

VITE_MUCHA_SCIENCE_WS_URL="ws://127.0.0.1:${pipeline_port}" \
  npm --prefix "$ROOT/web/ui" run dev -- --host 127.0.0.1 --port "$WEB_PORT" --strictPort
