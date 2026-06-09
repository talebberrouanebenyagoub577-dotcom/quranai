"""
Sahra AI configuration — loads from environment variables and .env file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")


class Config:
    BASE_DIR = BASE_DIR
    HOST = os.getenv("SAHRA_HOST", "0.0.0.0")
    PORT = int(os.getenv("SAHRA_PORT", "5000"))
    DEBUG = _env_bool("SAHRA_DEBUG", False)
    ENV = os.getenv("SAHRA_ENV", "production")

    OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")
    EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

    MEMORY_FILE = os.getenv("SAHRA_MEMORY_FILE", str(BASE_DIR / "quran_memory.json"))
    BRAIN_MEMORY_FILE = os.getenv("SAHRA_BRAIN_MEMORY_FILE", str(BASE_DIR / "brain_memory.json"))
    PRODUCT_MEMORY_FILE = os.getenv("SAHRA_PRODUCT_MEMORY_FILE", str(BASE_DIR / "product_memory.json"))
    CONVERSATIONS_FILE = os.getenv("SAHRA_CONVERSATIONS_FILE", str(BASE_DIR / "conversations.json"))
    EMBED_CACHE_FILE = os.getenv("SAHRA_EMBED_CACHE_FILE", str(BASE_DIR / "law_embeddings_cache.json"))

    LOG_DIR = Path(os.getenv("SAHRA_LOG_DIR", str(BASE_DIR / "logs")))
    LOG_FILE = LOG_DIR / "app.log"
    LOG_LEVEL = os.getenv("SAHRA_LOG_LEVEL", "INFO").upper()

    BACKUP_DIR = Path(os.getenv("SAHRA_BACKUP_DIR", str(BASE_DIR / "backups")))
    BACKUP_ON_STARTUP = _env_bool("SAHRA_BACKUP_ON_STARTUP", True)
    BACKUP_MAX_KEEP = int(os.getenv("SAHRA_BACKUP_MAX_KEEP", "30"))

    BEHIND_PROXY = _env_bool("SAHRA_BEHIND_PROXY", False)
    GUNICORN_WORKERS = int(os.getenv("SAHRA_GUNICORN_WORKERS", "2"))
    GUNICORN_TIMEOUT = int(os.getenv("SAHRA_GUNICORN_TIMEOUT", "120"))


config = Config()
