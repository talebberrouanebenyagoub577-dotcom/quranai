# حل مشاكل VPS — منصة صحرا

## فحص سريع (على VPS)

```bash
cd /opt/sahra
chmod +x check_vps.sh install_vps.sh start.sh restart.sh
./check_vps.sh
```

## أسباب شائعة لعدم عمل الموقع

### 1) الخدمة متوقفة

```bash
sudo systemctl status sahra-ai
sudo systemctl start sahra-ai
sudo journalctl -u sahra-ai -n 50
```

### 2) ملف `.env` أو `quran_memory.json` ناقص

```bash
ls -la .env quran_memory.json
cp .env.example .env
nano .env
```

### 3) Ollama غير شغّال (الموقع يفتح لكن المحادثة لا تعمل)

```bash
curl http://127.0.0.1:11434/api/tags
ollama serve &
ollama pull gemma3:1b
```

في `.env`:
```env
OLLAMA_BASE=http://127.0.0.1:11434
```

### 4) جدار الحماية يحجب المنفذ

```bash
sudo ufw allow 5000/tcp
sudo ufw allow 80/tcp
sudo ufw reload
```

وفي لوحة تحكم VPS (Hetzner, DigitalOcean, OVH...) افتح المنفذ 5000 أو 80.

### 5) صلاحيات الملفات

```bash
chmod +x install_vps.sh
./install_vps.sh
```

أو يدوياً:
```bash
sudo chown -R $USER:$USER /opt/sahra
chmod -R u+rwX logs backups
```

### 6) نهايات أسطر Windows (CRLF)

```bash
sed -i 's/\r$//' start.sh restart.sh check_vps.sh install_vps.sh
chmod +x *.sh
```

### 7) Nginx يعطي 502

تأكد أن gunicorn يعمل على 5000:
```bash
curl http://127.0.0.1:5000/health
```

إعداد Nginx:
```nginx
proxy_pass http://127.0.0.1:5000;
```

وفي `.env`:
```env
SAHRA_BEHIND_PROXY=true
```

## تثبيت تلقائي

```bash
cd /opt/sahra
./install_vps.sh
```

## اختبار من خارج VPS

```bash
curl http://IP-VPS:5000/health
```

يجب أن يظهر:
```json
{"status":"ok","checks":{"ollama":true,...}}
```

إذا `ollama: false` — ثبّت وشغّل Ollama.
