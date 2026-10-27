#!/usr/bin/env bash
# One command: backend on :8000 and the Vite frontend on :5173. Ctrl-C stops both.
# Usage: scripts/dev.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found. Install Python 3 first." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found. Install Node.js (includes npm) first." >&2; exit 1; }

# Venv: a stamp file marks a completed install, so an interrupted install is redone.
STAMP=".venv/.deps-installed"
if [ ! -x .venv/bin/python ] || [ ! -f "$STAMP" ] || [ backend/requirements.txt -nt "$STAMP" ]; then
  if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
    rm -rf .venv
    python3 -m venv .venv
  fi
  rm -f "$STAMP"
  .venv/bin/python -m pip install -q -r backend/requirements.txt
  touch "$STAMP"
fi

if [ ! -d frontend/node_modules ] || [ frontend/package.json -nt frontend/node_modules ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi

export FSA_DB="${FSA_DB:-$ROOT/safety-kb/_team/fsa.db}"
export FSA_KB_ROOT="${FSA_KB_ROOT:-$ROOT/safety-kb}"
mkdir -p "$(dirname "$FSA_DB")"

PIDS=()
kill_tree() {
  local p="$1" c
  for c in $(pgrep -P "$p" 2>/dev/null || true); do kill_tree "$c"; done
  kill "$p" 2>/dev/null || true
}
cleanup() {
  trap - EXIT INT TERM
  for p in ${PIDS[@]+"${PIDS[@]}"}; do kill_tree "$p"; done
  wait 2>/dev/null || true
  echo "Stopped."
}
trap cleanup EXIT
trap 'exit 130' INT TERM

.venv/bin/python -m backend.fsa --port 8000 &
PIDS+=($!)
(cd frontend && exec npm run dev -- --port 5173 --strictPort) &
PIDS+=($!)

wait_for() { # url name pid
  for _ in $(seq 1 60); do
    curl -fs -o /dev/null "$1" 2>/dev/null && return 0
    kill -0 "$3" 2>/dev/null || { echo "ERROR: $2 exited during start-up (port busy?)." >&2; return 1; }
    sleep 0.5
  done
  echo "ERROR: $2 did not become healthy at $1" >&2; return 1
}
wait_for http://localhost:8000/api/health Backend "${PIDS[0]}" || \
  wait_for http://localhost:8000/docs Backend "${PIDS[0]}"
wait_for http://localhost:5173/ Frontend "${PIDS[1]}"
echo "Backend  http://localhost:8000  (API docs /docs)"
echo "Frontend http://localhost:5173  (Ctrl-C to stop both)"
wait
