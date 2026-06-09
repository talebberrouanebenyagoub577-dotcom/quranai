"""
Deployment utilities: logging, data directories, memory bootstrap, backups.
"""

import json
import logging
import os
import shutil
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import config

LOG = logging.getLogger("sahra")
_RUNTIME_INITIALIZED = False


def setup_logging():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    LOG.info("Logging initialized | file=%s | level=%s", config.LOG_FILE, config.LOG_LEVEL)


def ensure_data_directories():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _write_json(path, payload):
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def ensure_memory_files():
    created = []

    quran_path = Path(config.MEMORY_FILE)
    if not quran_path.exists():
        LOG.critical(
            "Missing %s — deploy quran_memory.json before starting Sahra AI.",
            quran_path,
        )
        raise FileNotFoundError(f"Required law database not found: {quran_path}")

    brain_path = Path(config.BRAIN_MEMORY_FILE)
    if not brain_path.exists():
        _write_json(
            brain_path,
            {
                "version": 1,
                "laws_fingerprint": "",
                "neurons": {},
                "question_memory": {},
                "co_activation": {},
            },
        )
        created.append(str(brain_path))

    product_path = Path(config.PRODUCT_MEMORY_FILE)
    if not product_path.exists():
        _write_json(
            product_path,
            {
                "version": 2,
                "products": {},
                "learning": {
                    "category_buckets": {},
                    "raw_categories": {},
                    "keywords": {},
                    "matched_laws": {},
                },
            },
        )
        created.append(str(product_path))

    conversations_path = Path(config.CONVERSATIONS_FILE)
    if not conversations_path.exists():
        _write_json(
            conversations_path,
            {"version": 1, "active_id": None, "conversations": []},
        )
        created.append(str(conversations_path))

    if created:
        LOG.info("Created missing memory files: %s", ", ".join(created))


def _acquire_backup_lock():
    lock_path = config.BACKUP_DIR / ".backup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "w", encoding="utf-8")
    if os.name != "nt":
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
    return handle


def run_startup_backup():
    if not config.BACKUP_ON_STARTUP:
        LOG.info("Startup backup disabled")
        return None

    lock_handle = _acquire_backup_lock()
    if lock_handle is None:
        LOG.info("Startup backup skipped — another worker is backing up")
        return None

    try:
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        backup_root = config.BACKUP_DIR / timestamp
        backup_root.mkdir(parents=True, exist_ok=True)

        targets = [
            config.MEMORY_FILE,
            config.BRAIN_MEMORY_FILE,
            config.PRODUCT_MEMORY_FILE,
            config.CONVERSATIONS_FILE,
        ]

        copied = []
        for target in targets:
            source = Path(target)
            if not source.exists():
                continue
            destination = backup_root / source.name
            shutil.copy2(source, destination)
            copied.append(source.name)

        if copied:
            LOG.info("Startup backup created | dir=%s | files=%s", backup_root, ", ".join(copied))
        else:
            LOG.warning("Startup backup skipped — no memory files found")

        _prune_old_backups()
        return backup_root
    finally:
        lock_handle.close()


def _prune_old_backups():
    if config.BACKUP_MAX_KEEP <= 0:
        return

    backups = sorted(
        [p for p in config.BACKUP_DIR.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    for old in backups[config.BACKUP_MAX_KEEP :]:
        shutil.rmtree(old, ignore_errors=True)
        LOG.info("Removed old backup: %s", old)


def initialize_runtime():
    global _RUNTIME_INITIALIZED
    if _RUNTIME_INITIALIZED:
        return
    _RUNTIME_INITIALIZED = True

    ensure_data_directories()
    setup_logging()
    ensure_memory_files()
    run_startup_backup()
