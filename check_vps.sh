#!/usr/bin/env bash
# فحص تشخيصي لمنصة صحرا على VPS
set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[X]${NC} $1"; }

echo "=============================="
echo "  فحص VPS — منصة صحرا"
echo "=============================="
echo "المجلد: $APP_DIR"
echo

ISSUES=0

# 1) ملفات أساسية
for f in app.py wsgi.py config.py deploy_utils.py quran_memory.json requirements.txt; do
  if [[ -f "$f" ]]; then ok "ملف موجود: $f"; else fail "ملف ناقص: $f"; ISSUES=$((ISSUES+1)); fi
done

if [[ -f ".env" ]]; then
  ok "ملف .env موجود"
else
  fail "ملف .env غير موجود — انسخ .env.example إلى .env"
  ISSUES=$((ISSUES+1))
fi

# 2) بيئة Python
if [[ -d "venv" ]]; then
  ok "venv موجود"
  if [[ -x "venv/bin/gunicorn" ]]; then ok "gunicorn مثبت"; else fail "gunicorn غير مثبت — pip install -r requirements.txt"; ISSUES=$((ISSUES+1)); fi
else
  fail "venv غير موجود — python3 -m venv venv"
  ISSUES=$((ISSUES+1))
fi

# 3) صلاحيات الكتابة
for d in logs backups; do
  mkdir -p "$d"
  if [[ -w "$d" ]]; then ok "قابل للكتابة: $d/"; else fail "لا صلاحية كتابة: $d/"; ISSUES=$((ISSUES+1)); fi
done

for f in brain_memory.json product_memory.json conversations.json; do
  if [[ -f "$f" ]]; then
    if [[ -w "$f" ]]; then ok "قابل للكتابة: $f"; else fail "لا صلاحية كتابة: $f"; ISSUES=$((ISSUES+1)); fi
  else
    warn "سينشأ تلقائياً: $f"
  fi
done

# 4) المنفذ 5000
if command -v ss >/dev/null 2>&1; then
  PORT_CHECK=$(ss -lntp 2>/dev/null | grep ':5000 ' || true)
elif command -v netstat >/dev/null 2>&1; then
  PORT_CHECK=$(netstat -lntp 2>/dev/null | grep ':5000 ' || true)
else
  PORT_CHECK=""
fi

if [[ -n "$PORT_CHECK" ]]; then
  ok "المنفذ 5000 يعمل"
  echo "       $PORT_CHECK"
else
  warn "المنفذ 5000 غير نشط — الخادم متوقف؟"
fi

# 5) systemd
if systemctl list-unit-files 2>/dev/null | grep -q '^sahra-ai.service'; then
  STATUS=$(systemctl is-active sahra-ai 2>/dev/null || echo "unknown")
  if [[ "$STATUS" == "active" ]]; then ok "خدمة sahra-ai تعمل"; else fail "خدمة sahra-ai: $STATUS — شغّل: sudo systemctl start sahra-ai"; ISSUES=$((ISSUES+1)); fi
  echo
  echo "--- آخر سطور journalctl ---"
  sudo journalctl -u sahra-ai -n 15 --no-pager 2>/dev/null || true
else
  warn "خدمة systemd غير مثبتة — استخدم ./start.sh أو install_vps.sh"
fi

# 6) health محلي
echo
if curl -sf "http://127.0.0.1:5000/health" >/dev/null 2>&1; then
  ok "Health check: http://127.0.0.1:5000/health"
  curl -s "http://127.0.0.1:5000/health" | head -c 500
  echo
else
  fail "Health check فشل — التطبيق لا يستجيب على 127.0.0.1:5000"
  ISSUES=$((ISSUES+1))
fi

# 7) Ollama
OLLAMA_URL="${OLLAMA_BASE:-http://127.0.0.1:11434}"
if [[ -f ".env" ]]; then
  OLLAMA_URL=$(grep -E '^OLLAMA_BASE=' .env | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "$OLLAMA_URL")
fi
if curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
  ok "Ollama يعمل: $OLLAMA_URL"
else
  fail "Ollama لا يعمل: $OLLAMA_URL — المحادثة لن تعمل بدونه"
  ISSUES=$((ISSUES+1))
fi

# 8) جدار الحماية
if command -v ufw >/dev/null 2>&1; then
  UFW_STATUS=$(sudo ufw status 2>/dev/null || true)
  if echo "$UFW_STATUS" | grep -q "5000"; then ok "ufw يسمح بالمنفذ 5000"; else warn "ufw قد يحجب 5000 — sudo ufw allow 5000/tcp"; fi
fi

# 9) سجلات
if [[ -f "logs/error.log" ]]; then
  echo
  echo "--- آخر أخطاء gunicorn ---"
  tail -n 10 logs/error.log 2>/dev/null || true
fi
if [[ -f "logs/app.log" ]]; then
  echo
  echo "--- آخر سطور app.log ---"
  tail -n 10 logs/app.log 2>/dev/null || true
fi

echo
echo "=============================="
if [[ "$ISSUES" -eq 0 ]]; then
  ok "لا توجد مشاكل حرجة واضحة"
  echo "جرّب من المتصفح: http://$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):5000"
else
  fail "عدد المشاكل: $ISSUES — أصلحها ثم أعد التشغيل"
  echo "للتثبيت التلقائي: chmod +x install_vps.sh && ./install_vps.sh"
fi
echo "=============================="
