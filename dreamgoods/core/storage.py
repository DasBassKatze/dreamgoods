"""Файловое хранилище: папка на диске (STORAGE=local, разработка) или S3-совместимое облако (STORAGE=s3, релиз).

Файлы адресуются по содержимому: ключ = <организация>/<sha256[:2]>/<sha256>.<расширение>.
Один и тот же файл, загруженный дважды, хранится один раз; запись в таблице assets — на каждое использование.
"""
import hashlib
import io
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

from . import config
from ..db.models import Asset

log = logging.getLogger("dreamgoods")

EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/zip": ".zip",
       "text/csv": ".csv", "application/json": ".json"}

_client = None
_client_lock = threading.Lock()


def s3():
    global _client
    with _client_lock:
        if _client is None:
            _client = boto3.client(
                "s3", endpoint_url=config.S3_ENDPOINT, aws_access_key_id=config.S3_ACCESS_KEY,
                aws_secret_access_key=config.S3_SECRET_KEY, region_name=config.S3_REGION,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                              retries={"max_attempts": 5, "mode": "standard"}, connect_timeout=10, read_timeout=120))
        return _client


def ensure_bucket():
    """Готовит хранилище: папку на диске или бакет S3."""
    if config.STORAGE != "s3":
        config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.STORAGE_DIR / ".write_test"
        probe.write_bytes(b"ok")
        probe.unlink()
        return
    c = s3()
    try:
        c.head_bucket(Bucket=config.S3_BUCKET)
    except ClientError:
        c.create_bucket(Bucket=config.S3_BUCKET)
        log.info("S3: создан бакет %s", config.S3_BUCKET)


def _sniff(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"PK":
        return "application/zip"
    return "application/octet-stream"


def _image_meta(data):
    """(ширина, высота, время съёмки из EXIF)."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size                       # размер без распаковки пикселей
            if im.getexif().get(0x0112) in (5, 6, 7, 8):   # снимок повёрнут на 90° по EXIF
                w, h = h, w
            shot = None
            try:
                ex = im.getexif()
                v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
                if v:
                    shot = datetime.strptime(str(v).strip()[:19], "%Y:%m:%d %H:%M:%S")
            except Exception:
                pass
            return w, h, shot
    except Exception:
        return None, None, None


def put(s, org_id, data, kind, original_name="", mime=None, shot_at=None):
    """Кладёт байты в S3 (если такого содержимого ещё нет) и создаёт запись Asset. s — сессия БД."""
    sha = hashlib.sha256(data).hexdigest()
    mime = mime or _sniff(data)
    key = f"{org_id}/{sha[:2]}/{sha}{EXT.get(mime, '')}"
    _write(key, data, mime)
    w = h = None
    if mime.startswith("image/"):
        w, h, exif_shot = _image_meta(data)
        shot_at = shot_at or exif_shot
    a = Asset(org_id=org_id, kind=kind, storage_key=key, sha256=sha, mime=mime, bytes=len(data), width=w, height=h,
              original_name=original_name[:300], shot_at=shot_at)
    s.add(a)
    s.flush()
    return a


# небольшой кэш оригиналов в памяти: референсы одного товара читаются много раз подряд
_cache, _cache_size, _cache_lock = OrderedDict(), 0, threading.Lock()
CACHE_LIMIT = 300 * 1024 * 1024


def get(asset_or_key):
    key = asset_or_key if isinstance(asset_or_key, str) else asset_or_key.storage_key
    global _cache_size
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    data = _read(key)
    with _cache_lock:
        _cache[key] = data
        _cache_size += len(data)
        while _cache_size > CACHE_LIMIT and _cache:
            _, v = _cache.popitem(last=False)
            _cache_size -= len(v)
    return data


def _local(key):
    return config.STORAGE_DIR.joinpath(*key.split("/"))


def _write(key, data, mime):
    if config.STORAGE != "s3":
        p = _local(key)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        return
    c = s3()
    try:
        c.head_object(Bucket=config.S3_BUCKET, Key=key)
    except ClientError:
        c.put_object(Bucket=config.S3_BUCKET, Key=key, Body=data, ContentType=mime)


class Missing(LookupError):
    """Файла нет в хранилище (например, не скопирована папка data)."""


def _read(key):
    if config.STORAGE != "s3":
        try:
            return _local(key).read_bytes()
        except FileNotFoundError:
            raise Missing(f"файла нет в хранилище: {_local(key)}") from None
    try:
        return s3().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            raise Missing(f"файла нет в бакете {config.S3_BUCKET}: {key}") from None
        raise


def exists(key):
    if config.STORAGE != "s3":
        return _local(key).is_file()
    try:
        s3().head_object(Bucket=config.S3_BUCKET, Key=key)
        return True
    except ClientError:
        return False


def audit(sample=30):
    """Проверка при запуске: файлы, на которые ссылается база, на месте? Возвращает (проверено, нет)."""
    from sqlalchemy import select
    from .. import db
    with db.session() as s:
        keys = s.scalars(select(Asset.storage_key).order_by(Asset.created_at.desc()).limit(sample)).all()
    missing = [k for k in keys if not exists(k)]
    return len(keys), len(missing)


def upload_local_to_s3():
    """Переносит файлы из папки на диске в бакет S3 (ключи те же). Повторный запуск докачивает недостающее."""
    c = s3()
    ensure_s3 = config.STORAGE
    config.STORAGE = "s3"
    try:
        ensure_bucket()
    finally:
        config.STORAGE = ensure_s3
    files = [p for p in config.STORAGE_DIR.rglob("*") if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".part")]
    done = skipped = 0
    for n, p in enumerate(files, 1):
        key = p.relative_to(config.STORAGE_DIR).as_posix()
        try:
            c.head_object(Bucket=config.S3_BUCKET, Key=key)
            skipped += 1
        except ClientError:
            data = p.read_bytes()
            c.put_object(Bucket=config.S3_BUCKET, Key=key, Body=data, ContentType=_sniff(data))
            done += 1
        if n % 200 == 0:
            log.info("Перенос в S3: %d/%d", n, len(files))
    log.info("Перенос в S3 завершён: загружено %d, уже были %d. Теперь поставьте в .env STORAGE=s3", done, skipped)


def remove(key):
    """Удаляет файл из хранилища (и из кэшей). Вызывающий сам проверяет, что на файл больше никто не ссылается."""
    global _cache_size
    with _cache_lock:
        v = _cache.pop(key, None)
        if v is not None:
            _cache_size -= len(v)
    with _thumb_lock:
        for k in [k for k in _thumbs if k[0] == key]:
            _thumbs.pop(k, None)
    if config.STORAGE != "s3":
        try:
            _local(key).unlink()
        except FileNotFoundError:
            pass
        return
    s3().delete_object(Bucket=config.S3_BUCKET, Key=key)


_thumbs, _thumb_lock = OrderedDict(), threading.Lock()


def thumb(asset, w):
    """JPEG-превью шириной до w (кэш в памяти)."""
    k = (asset.storage_key, w)
    with _thumb_lock:
        if k in _thumbs:
            _thumbs.move_to_end(k)
            return _thumbs[k]
    from ..ai.images import DECODE_SLOTS, open_small
    with DECODE_SLOTS:
        with open_small(get(asset), w) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((w, w * 2), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
    data = buf.getvalue()
    with _thumb_lock:
        _thumbs[k] = data
        while len(_thumbs) > 2000:
            _thumbs.popitem(last=False)
    return data
