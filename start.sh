#!/usr/bin/env bash
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

fail() { echo "[sahra-start][خطأ] $1" >&2; exit 1; }
step() { echo "[sahra-start] $1"; }

fix_crlf() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  sed -i 's/\r$//' "$f" 2>/dev/null || {
    tr -d '\r' < "$f" > "$f.tmp"
    mv "$f.tmp" "$f"
  }
}

load_env_file() {
  local file="$1"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//$'\r'/}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    export "$line"
  done < "$file"
}

step "المجلد: $APP_DIR"

fix_crlf ".env"
fix_crlf ".env.example"

if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
    fix_crlf ".env"
    step "تم إنشاء .env من .env.example"
  else
    fail "ملف .env غير موجود — انسخ .env.example إلى .env"
  fi
fi

if [[ ! -f "quran_memory.json" ]]; then
  fail "quran_memory.json غير موجود — ارفع قاعدة قوانين صحرا أولاً"
fi

if [[ ! -d "venv" ]]; then
  step "إنشاء venv..."
  python3 -m venv venv || fail "تعذر إنشاء venv — ثبّت: apt install python3-venv"
fi

if [[ ! -x "venv/bin/gunicorn" ]]; then
  step "تثبيت المتطلبات..."
  ./venv/bin/pip install --upgrade pip || fail "فشل pip upgrade"
  ./venv/bin/pip install -r requirements.txt || fail "فشل pip install -r requirements.txt"
fi

if [[ ! -x "venv/bin/gunicorn" ]]; then
  fail "gunicorn غير مثبت بعد pip install"
fi

load_env_file ".env"

HOST="${SAHRA_HOST:-0.0.0.0}"
PORT="${SAHRA_PORT:-5000}"
WORKERS="${SAHRA_GUNICORN_WORKERS:-2}"
TIMEOUT="${SAHRA_GUNICORN_TIMEOUT:-120}"

mkdir -p logs backups || fail "تعذر إنشاء logs/ أو backups/ — تحقق من الصلاحيات"
touch logs/access.log logs/error.log 2>/dev/null || true

step "فحص تحميل التطبيق..."
if ! ./venv/bin/python -c "from wsgi import app" 2>logs/start_error.log; then
  echo "--- خطأ Python ---" >&2
  cat logs/start_error.log >&2 || true
  fail "فشل تحميل wsgi:app — راجع logs/start_error.log"
fi

step "تشغيل gunicorn على ${HOST}:${PORT} (workers=${WORKERS})"
exec ./venv/bin/gunicorn \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT" \
  --bind "${HOST}:${PORT}" \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  wsgi:app
