# Sahra AI — VPS Deployment Guide

## Requirements

- Ubuntu 22.04+ (or any Linux VPS)
- Python 3.11+
- Ollama running on the same VPS or reachable host
- `quran_memory.json` deployed (read-only law database)

## 1. Upload project

```bash
sudo mkdir -p /opt/sahra
sudo chown $USER:$USER /opt/sahra
rsync -av --exclude venv --exclude logs --exclude backups ./ user@your-vps:/opt/sahra/
```

Required files on the VPS:

- `quran_memory.json` (do not edit on server)
- `app.py`, `brain.py`, `config.py`, `deploy_utils.py`, `wsgi.py`
- `product_analyzer.py`, `conversations.py`
- `templates/`, `static/`
- `requirements.txt`, `.env.example`

## 2. Install dependencies

```bash
cd /opt/sahra
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure environment

```bash
cp .env.example .env
nano .env
```

Minimum production settings:

```env
SAHRA_ENV=production
SAHRA_HOST=0.0.0.0
SAHRA_PORT=5000
SAHRA_DEBUG=false
SAHRA_BEHIND_PROXY=true
OLLAMA_BASE=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:1b
```

Set `SAHRA_BEHIND_PROXY=true` when using Nginx in front of the app.

## 4. First run checks

```bash
source venv/bin/activate
python -c "from deploy_utils import initialize_runtime; initialize_runtime()"
./start.sh
```

Open:

- `http://YOUR_VPS_IP:5000`
- `http://YOUR_VPS_IP:5000/health` → `{"status":"ok"}`

## 5. systemd — automatic startup after reboot

```bash
sudo cp sahra-ai.service /etc/systemd/system/sahra-ai.service
sudo nano /etc/systemd/system/sahra-ai.service
```

Update paths if needed:

- `WorkingDirectory=/opt/sahra`
- `User=` / `Group=` (your Linux user)
- `ExecStart=` gunicorn path

```bash
sudo chown -R www-data:www-data /opt/sahra/logs /opt/sahra/backups
sudo chown www-data:www-data /opt/sahra/brain_memory.json /opt/sahra/product_memory.json /opt/sahra/conversations.json
sudo systemctl daemon-reload
sudo systemctl enable sahra-ai
sudo systemctl start sahra-ai
sudo systemctl status sahra-ai
```

After reboot:

```bash
sudo systemctl is-enabled sahra-ai
curl http://127.0.0.1:5000/health
```

## 6. Nginx reverse proxy (recommended)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable HTTPS with Certbot after DNS is configured.

## 7. Logs

| File | Purpose |
|------|---------|
| `logs/app.log` | Application, Amazon analysis, neural memory |
| `logs/access.log` | Gunicorn HTTP access |
| `logs/error.log` | Gunicorn errors |

```bash
tail -f /opt/sahra/logs/app.log
```

## 8. Backups

On each startup, Sahra copies to `backups/YYYY-MM-DD_HH-MM-SS/`:

- `quran_memory.json`
- `brain_memory.json`
- `product_memory.json`
- `conversations.json`

Old backups are pruned (default: keep 30).

## 9. Memory files

Created automatically if missing:

- `brain_memory.json`
- `product_memory.json`
- `conversations.json`

`quran_memory.json` must be deployed manually. Sahra will not modify it.

## 10. Scripts

| Script | Purpose |
|--------|---------|
| `./start.sh` | Start production server with gunicorn |
| `./restart.sh` | Restart via systemd or local gunicorn |

## 11. Firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# Only if exposing Flask directly:
sudo ufw allow 5000/tcp
sudo ufw enable
```

## 12. Ollama on VPS

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:1b
ollama pull nomic-embed-text
```

Ensure `OLLAMA_BASE` in `.env` points to the running Ollama instance.

## Troubleshooting

```bash
sudo journalctl -u sahra-ai -f
curl http://127.0.0.1:5000/health
```

- **502 Bad Gateway** — check `systemctl status sahra-ai` and Ollama
- **Empty law answers** — verify `quran_memory.json` exists and is readable
- **Permission errors** — fix ownership of `logs/`, `backups/`, and writable JSON files
