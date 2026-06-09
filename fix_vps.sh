#!/usr/bin/env bash
# إصلاح سريع لـ VPS: CRLF + venv + systemd
set -euo pipefail

cd /opt/quranai

echo "=== إصلاح CRLF ==="
for f in .env .env.example start.sh restart.sh install_vps.sh fix_service.sh; do
  if [[ -f "$f" ]]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || tr -d '\r' < "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "  fixed: $f"
  fi
done

echo "=== تثبيت Python deps ==="
apt-get install -y python3 python3-venv python3-pip curl 2>/dev/null || true
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "=== صلاحيات ==="
chmod +x start.sh restart.sh
mkdir -p logs backups

echo "=== إعادة تشغيل الخدمة ==="
systemctl restart sahra-ai
sleep 3
systemctl status sahra-ai --no-pager
curl -s http://127.0.0.1:5000/health
echo
