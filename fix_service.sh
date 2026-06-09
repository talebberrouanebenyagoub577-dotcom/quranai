#!/usr/bin/env bash
# إصلاح خدمة systemd عندما يكون المشروع في /opt/quranai
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
APP_USER="${SUDO_USER:-${USER:-root}}"

echo "إصلاح sahra-ai.service"
echo "المجلد: $APP_DIR"

if [[ ! -f "start.sh" ]]; then
  echo "[خطأ] start.sh غير موجود في $APP_DIR"
  exit 1
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "[!] تم إنشاء .env من .env.example"
fi

for f in .env .env.example start.sh restart.sh install_vps.sh fix_service.sh; do
  [[ -f "$f" ]] && sed -i 's/\r$//' "$f" 2>/dev/null || true
done
chmod +x start.sh restart.sh fix_service.sh install_vps.sh 2>/dev/null || chmod +x start.sh

sed "s|/opt/quranai|$APP_DIR|g; s|/opt/sahra|$APP_DIR|g; s|User=root|User=$APP_USER|g; s|Group=root|Group=$APP_USER|g" sahra-ai.service \
  | tee /etc/systemd/system/sahra-ai.service >/dev/null

systemctl daemon-reload
systemctl enable sahra-ai
systemctl restart sahra-ai

sleep 2
systemctl status sahra-ai --no-pager || true
curl -s http://127.0.0.1:5000/health || echo "health check failed"
