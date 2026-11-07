"""Logical database checkpoint before a new application version can run migrations."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4


def version_tuple(value):
    try:
        return tuple(int(n) for n in value.split("."))
    except (AttributeError, ValueError):
        raise RuntimeError("Не удалось прочитать версию локальной базы. Данные сохранены.")


def prepare_upgrade(root, pg, port, env, version, existing, run):
    root, pg = Path(root), Path(pg)
    marker = root / "application.json"
    previous = json.loads(marker.read_text(encoding="utf-8")).get("version") if marker.exists() else None
    if previous and version_tuple(previous) > version_tuple(version):
        raise RuntimeError(f"Эта база уже открывалась в DreamGoods {previous}. Установите эту или более новую версию. Данные сохранены.")
    if not existing or previous == version:
        return None
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    folder = root / "backups" / name
    folder.mkdir(parents=True)
    temporary, dump = folder / "database.dump.part", folder / "database.dump"
    ext = ".exe" if (pg / "pg_dump.exe").exists() else ""
    try:
        run([pg / ("pg_dump" + ext), "-h", "127.0.0.1", "-p", str(port), "-U", "dreamgoods",
             "--format=custom", "--no-owner", "--file", temporary, "dreamgoods"], env=env)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("Резервная копия базы пуста")
        run([pg / ("pg_restore" + ext), "--list", temporary], env=env)
        temporary.replace(dump)
        (folder / "manifest.json").write_text(json.dumps({"from_version": previous or "legacy",
            "to_version": version, "postgres_major": 17, "created_at": datetime.now(timezone.utc).isoformat(),
            "contents": "database only; photos remain in the sibling files directory"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return dump
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Не удалось создать резервную копию базы перед обновлением. Запуск остановлен; исходные данные сохранены. Проверьте свободное место и права на папку данных.") from exc


def mark_version(root, version):
    root = Path(root)
    temporary = root / "application.json.tmp"
    temporary.write_text(json.dumps({"version": version}), encoding="utf-8")
    temporary.replace(root / "application.json")
