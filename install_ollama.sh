#!/usr/bin/env bash
# تثبيت وتشغيل Ollama لمنصة صحرا
set -euo pipefail

echo "=============================="
echo "  تثبيت Ollama لصحرا"
echo "=============================="

if ! command -v ollama >/dev/null 2>&1; then
  echo "[*] تثبيت Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "[OK] Ollama مثبت"
fi

echo "[*] تشغيل خدمة Ollama..."
systemctl enable ollama
systemctl start ollama
sleep 3

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "[!] الخدمة لم تبدأ — جرّب: systemctl status ollama"
  exit 1
fi

echo "[OK] Ollama يعمل"

MODEL="${OLLAMA_MODEL:-gemma3:1b}"
EMBED="${EMBED_MODEL:-nomic-embed-text}"

echo "[*] تحميل النموذج: $MODEL (قد يستغرق وقتاً)"
ollama pull "$MODEL"

echo "[*] تحميل نموذج embeddings: $EMBED"
ollama pull "$EMBED" || echo "[!] embeddings اختياري — يمكن تخطيه"

echo
echo "[OK] جاهز"
echo "اختبر: curl http://127.0.0.1:11434/api/tags"
echo "ثم أعد تشغيل صحرا: systemctl restart sahra-ai"
