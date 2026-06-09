#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if systemctl list-unit-files | grep -q '^sahra-ai.service'; then
  echo "Restarting systemd service sahra-ai..."
  sudo systemctl restart sahra-ai
  sudo systemctl status sahra-ai --no-pager
  exit 0
fi

echo "systemd service not installed — restarting local gunicorn..."
pkill -f "gunicorn.*wsgi:app" || true
sleep 2
exec ./start.sh
