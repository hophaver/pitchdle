#!/usr/bin/env bash
# Run Pitchdle on localhost: creates .venv on first run, installs deps, starts uvicorn with reload.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Pitchdle needs Python 3.12+ (found $("$PY" --version 2>&1)). Set PYTHON=/path/to/python3.12." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv"
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.deps-installed ] || [ requirements.txt -nt .venv/.deps-installed ]; then
  echo "Installing requirements"
  .venv/bin/pip install -q -r requirements.txt
  touch .venv/.deps-installed
fi

if [ -f .env ]; then set -a; . ./.env; set +a; fi
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "Pitchdle on http://${HOST}:${PORT}/play  (host: /host, admin: /admin, wall: /wall)"
exec .venv/bin/uvicorn app.main:app --reload --reload-dir app --host "$HOST" --port "$PORT"
