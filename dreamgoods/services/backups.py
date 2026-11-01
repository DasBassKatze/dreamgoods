"""Consistent DB dump + immutable asset files, checksums, optional isolated restore drill."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from uuid import uuid4
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from .. import db
from ..core import config, storage
from ..core.logs import log
from ..db.models import Asset


def pgtool(name):
    base = config.app_env("PG_BIN", "")
    return str(Path(base) / name) if base else name


def pg_env(url):
    u = make_url(str(url))
    env = dict(os.environ)
    env.update(PGHOST=u.host or "localhost", PGPORT=str(u.port or 5432), PGUSER=u.username or "studio",
        PGPASSWORD=u.password or "", PGDATABASE=u.database or "studio")
    return env


def run_pg(args, url):
    subprocess.run([pgtool(args[0]), *args[1:]], env=pg_env(url), check=True, capture_output=True, timeout=3600)


def verify_checksums(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    for name, digest in manifest["checksums"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("unsafe backup path")
        if not path.is_file() or sha_file(path) != digest:
            raise ValueError(f"backup checksum mismatch: {name}")
    return manifest


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_restore(folder):
    folder = Path(folder)
    verify_checksums(folder)
    name = "dg_verify_" + uuid4().hex[:20]
    url = make_url(config.DATABASE_URL)
    maintenance = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = url.set(database=name)
    try:
        with maintenance.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
        run_pg(["pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "--dbname", name,
            str(folder / "database.dump")], target.render_as_string(hide_password=False))
        restored = create_engine(target)
        try:
            with restored.connect() as c:
                count = c.scalar(text("SELECT count(*) FROM alembic_version"))
                if count != 1:
                    raise ValueError("restored database schema is invalid")
                for key, sha in c.execute(text("SELECT storage_key, sha256 FROM assets")):
                    path = (folder / "files" / key).resolve()
                    if not path.is_relative_to((folder / "files").resolve()) or not path.is_file() or sha_file(path) != sha:
                        raise ValueError("restored database references a missing or damaged asset")
        finally:
            restored.dispose()
    finally:
        with maintenance.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        maintenance.dispose()


def create_backup(verify=True):
    from datetime import datetime, timezone
    root = Path(config.app_env("BACKUP_DIR", str(config.ROOT / "backups")))
    root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]
    staging = Path(tempfile.mkdtemp(prefix=".partial_", dir=root))
    try:
        run_pg(["pg_dump", "--format=custom", "--no-owner", "--file", str(staging / "database.dump")], config.DATABASE_URL)
        # Asset files are immutable; copying a superset after the dump is safe.
        with db.session() as s:
            assets = s.execute(select(Asset.storage_key, Asset.sha256).distinct()).all()
        for key, sha in assets:
            target = (staging / "files" / key).resolve()
            if not target.is_relative_to((staging / "files").resolve()):
                raise ValueError("unsafe asset key")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(storage.get(key))
            if sha_file(target) != sha:
                raise ValueError("source asset checksum mismatch")
        checksums = {str(p.relative_to(staging)): sha_file(p) for p in staging.rglob("*") if p.is_file()}
        (staging / "manifest.json").write_text(json.dumps({"version":1, "checksums":checksums}, indent=2))
        verify_checksums(staging)
        run_pg(["pg_restore", "--list", str(staging / "database.dump")], config.DATABASE_URL)
        if verify:
            verify_restore(staging)
        final = root / name
        staging.rename(final)
        keep = max(1, int(config.app_env("BACKUP_KEEP", "7")))
        for old in sorted((p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")), reverse=True)[keep:]:
            if (old / "manifest.json").is_file():
                shutil.rmtree(old)
        log.info("Резервная копия завершена и проверена: %s (полное восстановление: %s)", final, verify)
        return final
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _loop():
    hours = float(config.app_env("BACKUP_HOURS", "24"))
    if hours <= 0:
        return
    while True:
        try:
            # Session lock prevents simultaneous backups on multiple server instances.
            with db.engine.connect() as c:
                locked = c.scalar(text("SELECT pg_try_advisory_lock(840622)"))
                try:
                    if locked:
                        root = Path(config.app_env("BACKUP_DIR", str(config.ROOT / "backups")))
                        latest = max((p.stat().st_mtime for p in root.glob("*/manifest.json")), default=0)
                        if time.time() - latest >= hours * 3600:
                            create_backup(config.app_env("BACKUP_VERIFY_RESTORE", "true").lower() == "true")
                finally:
                    if locked:
                        c.execute(text("SELECT pg_advisory_unlock(840622)"))
        except Exception as e:
            # Do not log subprocess arguments/env: may contain credentials.
            log.error("Резервная копия не создана (%s). Проверьте pg_dump/pg_restore, BACKUP_DIR и право CREATEDB.", type(e).__name__)
        time.sleep(min(300, hours * 3600))


def start():
    threading.Thread(target=_loop, daemon=True, name="backups").start()
