#!/usr/bin/env bash
# نشر طبقة فحص الذاكرة على VPS — /opt/quranai
set -euo pipefail

APP_DIR="/opt/quranai"
cd "$APP_DIR"

echo "=== نشر Memory Inspector ==="
echo "المجلد: $APP_DIR"

required_files=(memory_inspector.py app.py)
for f in "${required_files[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "[خطأ] ملف ناقص: $APP_DIR/$f"
    echo "       ارفعه من PC أو نفّذ: git pull"
    exit 1
  fi
done

if ! grep -q 'admin/memory' app.py; then
  echo "[خطأ] route /admin/memory غير موجود في app.py"
  exit 1
fi

if ! grep -q 'memory_inspector' app.py; then
  echo "[خطأ] import memory_inspector غير موجود في app.py"
  exit 1
fi

./venv/bin/python -c "from memory_inspector import get_admin_memory_snapshot; from wsgi import app; print('import OK')" \
  || { echo "[خطأ] فشل تحميل memory_inspector أو wsgi"; exit 1; }

systemctl restart sahra-ai
sleep 3

echo
echo "--- اختبار endpoint ---"
curl -sf "http://127.0.0.1:5000/admin/memory" | head -c 400
echo
echo
echo "[OK] /admin/memory يعمل"
