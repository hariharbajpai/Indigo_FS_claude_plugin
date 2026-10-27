#!/usr/bin/env bash
# Development only: the dashboard server on :4810 (no token) plus the Vite dev server on :5173 with live reload.
# In Claude Code you never need this: /flight-safety-agents:start runs the bundled dashboard for you.
# Usage: scripts/dev.sh        (KB: ./safety-kb, override with FSA_KB_ROOT)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found. Install Python 3.9+ first." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found. Install Node.js (includes npm) first." >&2; exit 1; }

if [ ! -d frontend/node_modules ] || [ frontend/package.json -nt frontend/node_modules ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi

export FSA_KB_ROOT="${FSA_KB_ROOT:-$ROOT/safety-kb}"

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

python3 -m backend.fsa serve --port 4810 --token "" &
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
wait_for http://localhost:4810/api/health Backend "${PIDS[0]}"
wait_for http://localhost:5173/ Frontend "${PIDS[1]}"
echo "Dashboard server http://localhost:4810  (bundled UI + API)"
echo "Dev UI           http://localhost:5173  (live reload; Ctrl-C stops both)"
wait
