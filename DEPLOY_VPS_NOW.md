# تثبيت صحرا على VPS — خطوة بخطوة

نتيجة الفحص عندك تعني: **المشروع غير مرفوع وغير مثبت على السيرفر.**

```
Unit sahra-ai.service could not be found  → الخدمة غير مثبتة
./check_vps.sh: No such file              → أنت في ~ وليس مجلد المشروع
curl port 5000 failed                     → التطبيق غير شغّال
```

---

## الخطوة 1 — من الكمبيوتر (Windows)

ارفع المشروع كاملاً إلى VPS:

```powershell
scp -r "C:\Users\pc\Desktop\quranai" root@IP-VPS:/opt/sahra
```

استبدل `IP-VPS` بعنوان سيرفر `bob-prod-01`.

**مهم:** تأكد أن `quran_memory.json` موجود داخل المجلد قبل الرفع.

---

## الخطوة 2 — على VPS (bob-prod-01)

```bash
cd /opt/sahra
ls -la app.py quran_memory.json install_vps.sh
```

إذا ظهرت الملفات:

```bash
apt update
apt install -y python3 python3-venv python3-pip curl
sed -i 's/\r$//' *.sh
chmod +x install_vps.sh check_vps.sh start.sh restart.sh
./install_vps.sh
```

---

## الخطوة 3 — Ollama (ضروري للمحادثة)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:1b
systemctl enable ollama
systemctl start ollama
```

---

## الخطوة 4 — فتح المنفذ

```bash
ufw allow 22/tcp
ufw allow 5000/tcp
ufw allow 80/tcp
ufw --force enable
```

وفي لوحة تحكم VPS (Firewall / Security Group) افتح المنفذ **5000**.

---

## الخطوة 5 — اختبار

```bash
cd /opt/sahra
curl http://127.0.0.1:5000/health
sudo systemctl status sahra-ai
./check_vps.sh
```

من المتصفح:

```
http://IP-VPS:5000
```

---

## إذا `cd /opt/sahra` يقول لا يوجد

المشروع لم يُرفع. أعد الخطوة 1 من Windows.

## أوامر مفيدة

```bash
sudo systemctl restart sahra-ai
sudo journalctl -u sahra-ai -f
tail -f /opt/sahra/logs/app.log
```
