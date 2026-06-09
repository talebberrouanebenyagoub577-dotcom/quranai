#!/usr/bin/env bash
# تثبيت منصة صحرا على VPS
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
APP_USER="${SUDO_USER:-${USER:-root}}"

echo "=============================="
echo "  تثبيت صحرا على VPS"
echo "=============================="
echo "المجلد: $APP_DIR"
echo "المستخدم: $APP_USER"
echo

if [[ ! -f "app.py" || ! -f "wsgi.py" ]]; then
  echo "[خطأ] لست في مجلد صحرا الصحيح"
  echo "       انسخ المشروع إلى /opt/sahra ثم أعد التشغيل"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[*] تثبيت Python3..."
  apt-get update -qq
  apt-get install -y python3 python3-venv python3-pip curl
fi

if [[ ! -f "quran_memory.json" ]]; then
  echo "[خطأ] quran_memory.json غير موجود — ارفعه أولاً"
  exit 1
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "[!] تم إنشاء .env من .env.example — راجع الإعدادات"
fi

# إصلاح نهايات الأسطر Windows
for f in start.sh restart.sh check_vps.sh install_vps.sh; do
  if [[ -f "$f" ]]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || sed -i '' 's/\r$//' "$f" 2>/dev/null || true
    chmod +x "$f"
  fi
done

# Python venv
if [[ ! -d "venv" ]]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# مجلدات وملفات
mkdir -p logs backups
touch logs/access.log logs/error.log logs/app.log

for f in brain_memory.json product_memory.json conversations.json; do
  if [[ ! -f "$f" ]]; then
    python3 -c "
from deploy_utils import ensure_memory_files, ensure_data_directories, setup_logging
ensure_data_directories()
setup_logging()
ensure_memory_files()
"
    break
  fi
done

# صلاحيات
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod -R u+rwX "$APP_DIR/logs" "$APP_DIR/backups"
chmod u+rw "$APP_DIR"/*.json 2>/dev/null || true

# systemd
SERVICE_PATH="/etc/systemd/system/sahra-ai.service"
sed "s|/opt/quranai|$APP_DIR|g; s|/opt/sahra|$APP_DIR|g; s|User=root|User=$APP_USER|g; s|Group=root|Group=$APP_USER|g" sahra-ai.service | tee "$SERVICE_PATH" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable sahra-ai
sudo systemctl restart sahra-ai

sleep 3

echo
if curl -sf "http://127.0.0.1:5000/health" >/dev/null; then
  echo "[OK] الصحرا تعمل على http://127.0.0.1:5000"
  PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
  echo "[OK] من الإنترنت: http://${PUBLIC_IP}:5000"
  echo
  echo "للفحص: ./check_vps.sh"
  echo "للسجلات: sudo journalctl -u sahra-ai -f"
else
  echo "[X] التطبيق لم يبدأ — شغّل: ./check_vps.sh"
  journalctl -u sahra-ai -n 30 --no-pager 2>/dev/null || true
  echo
  echo "--- آخر سطور logs/error.log ---"
  tail -n 20 logs/error.log 2>/dev/null || true
  exit 1
fi

if ! curl -sf "${OLLAMA_BASE:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1; then
  echo
  echo "[!] Ollama غير شغّال — الموقع يفتح لكن المحادثة لن تعمل"
  echo "    ثبّت Ollama: curl -fsSL https://ollama.com/install.sh | sh"
  echo "    ثم: ollama pull gemma3:1b"
fi
