#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [[ ! -f ".env" ]]; then
  echo "Missing .env — copy .env.example to .env and configure it."
  exit 1
fi

if [[ ! -d "venv" ]]; then
  echo "Missing virtual environment — run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

set -a
source .env
set +a

HOST="${SAHRA_HOST:-0.0.0.0}"
PORT="${SAHRA_PORT:-5000}"
WORKERS="${SAHRA_GUNICORN_WORKERS:-2}"

mkdir -p logs backups

echo "Starting Sahra AI on ${HOST}:${PORT}"
exec ./venv/bin/gunicorn \
  --workers "$WORKERS" \
  --bind "${HOST}:${PORT}" \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  wsgi:app
