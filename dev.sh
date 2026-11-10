#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
FLASK="$ROOT_DIR/.venv/bin/flask"
ANGULAR="$ROOT_DIR/adminpro/node_modules/.bin/ng"
backend_pid=""

if [[ ! -x "$PYTHON" || ! -x "$FLASK" ]]; then
  echo "Backend environment is missing. Create .venv and install requirements.txt first." >&2
  exit 1
fi

if [[ ! -x "$ANGULAR" ]]; then
  echo "Frontend dependencies are missing. Run 'npm ci' inside adminpro/ first." >&2
  exit 1
fi

cleanup() {
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Building Angular bundle into static/ ..."
(cd "$ROOT_DIR/adminpro" && npm run build)

(
  cd "$ROOT_DIR"
  "$FLASK" --app main:app run --debug --no-reload --host 127.0.0.1 --port 3000
) &
backend_pid=$!

echo "Flask debug server: http://127.0.0.1:3000"
echo "Angular dev server: http://127.0.0.1:4200"
echo "Press Ctrl+C to stop both servers."

cd "$ROOT_DIR/adminpro"
"$ANGULAR" serve --host 127.0.0.1 --port 4200
