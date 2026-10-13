"""Настройки окружения. Читаются из переменных окружения и файла .env рядом с проектом."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def env(key, default=""):
    return os.environ.get(key, default)


DATABASE_URL = env("DATABASE_URL", "postgresql+psycopg://studio:studio@127.0.0.1:5432/studio")
# Хранилище файлов: local — папка на диске (разработка), s3 — S3-совместимое облако (релиз: Yandex Object Storage,
# Selectel, VK Cloud и т. п.). Структура ключей одинаковая, переносится командой run_dreamgoods.py --upload-to-s3
STORAGE = env("STORAGE", "local").strip().lower()
STORAGE_DIR = Path(env("STORAGE_DIR") or str(ROOT / "data" / "files"))
S3_ENDPOINT = env("S3_ENDPOINT", "https://storage.yandexcloud.net")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", "studio")
S3_SECRET_KEY = env("S3_SECRET_KEY", "studio-secret")
S3_BUCKET = env("S3_BUCKET", "studio")
S3_REGION = env("S3_REGION", "us-east-1")
POLZA_API_KEY = env("POLZA_API_KEY", "")


def app_env(name, default):
    """DREAMGOODS_<name>; старые имена STUDIO_<name> из прежних .env тоже понимаются."""
    return env(f"DREAMGOODS_{name}") or env(f"STUDIO_{name}", default)


HOST = app_env("HOST", "127.0.0.1")
PORT = int(app_env("PORT", "8765"))
WORKERS = int(app_env("WORKERS", "4"))
LOG_DIR = Path(app_env("LOG_DIR", str(ROOT / "logs")))
EXPORT_DIR = Path(app_env("EXPORT_DIR", str(ROOT / "exports")))
