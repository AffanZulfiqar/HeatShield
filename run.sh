#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
PORT="${PORT:-8000}"
echo "Scorched on http://localhost:${PORT}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" "$@"
