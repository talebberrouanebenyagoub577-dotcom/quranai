#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

fail() { echo "[خطأ] $1" >&2; exit 1; }

fix_crlf() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  sed -i 's/\r$//' "$f" 2>/dev/null || tr -d '\r' < "$f" > "$f.tmp" && mv "$f.tmp" "$f"
}

fix_crlf ".env"
fix_crlf ".env.example"
fix_crlf "$0"

if [[ ! -f ".env" ]]; then
  fail "ملف .env غير موجود — انسخ .env.example إلى .env"
fi

if [[ ! -f "quran_memory.json" ]]; then
  fail "quran_memory.json غير موجود — ارفع قاعدة قوانين صحرا أولاً"
fi

if [[ ! -d "venv" ]]; then
  echo "[*] إنشاء venv..."
  python3 -m venv venv || fail "تعذر إنشاء venv — ثبّت python3-venv"
fi

if [[ ! -x "venv/bin/gunicorn" ]]; then
  echo "[*] تثبيت المتطلبات..."
  ./venv/bin/pip install --upgrade pip
  ./venv/bin/pip install -r requirements.txt || fail "فشل pip install -r requirements.txt"
fi

if [[ ! -x "venv/bin/gunicorn" ]]; then
  fail "gunicorn غير مثبت بعد pip install"
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

HOST="${SAHRA_HOST:-0.0.0.0}"
PORT="${SAHRA_PORT:-5000}"
WORKERS="${SAHRA_GUNICORN_WORKERS:-2}"
TIMEOUT="${SAHRA_GUNICORN_TIMEOUT:-120}"

mkdir -p logs backups
touch logs/access.log logs/error.log 2>/dev/null || true

echo "Starting Sahra AI on ${HOST}:${PORT} (workers=${WORKERS}, timeout=${TIMEOUT}s)"
exec ./venv/bin/gunicorn \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT" \
  --bind "${HOST}:${PORT}" \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  wsgi:app
