"""Запуск DreamGoods:  python run_dreamgoods.py [--debug] [--no-browser] [--import-legacy ПАПКА] [--reset-master]

Перед первым запуском поднимите PostgreSQL:  docker compose up -d
"""
import os
import sys
import threading
import webbrowser



def _limit_malloc_arenas():
    """Linux (сервер): сотни потоков заданий × по арене памяти glibc на поток = гигабайты «занятой» памяти после
    обработки картинок. Две арены + периодический malloc_trim держат процесс компактным. Переменная читается только
    при старте процесса, поэтому перезапускаем себя с ней. На Windows не нужно."""
    if sys.platform.startswith("linux") and "MALLOC_ARENA_MAX" not in os.environ:
        os.environ["MALLOC_ARENA_MAX"] = "2"
        os.execv(sys.executable, [sys.executable] + sys.argv)

from dreamgoods.core import config
from dreamgoods.core.logs import log, setup_logging


def _has(module):
    import importlib.util
    return importlib.util.find_spec(module) is not None


def main(stop_event=None):
    setup_logging()
    where = f"S3 {config.S3_ENDPOINT}/{config.S3_BUCKET}" if config.STORAGE == "s3" else f"папка {config.STORAGE_DIR}"
    log.info("DreamGoods %s · база %s · файлы: %s", __import__("dreamgoods").__version__, config.DATABASE_URL.split("@")[-1], where)
    # 0. библиотеки Python — иначе ошибка выглядит как «нет базы»
    missing = [m for m in ("sqlalchemy", "psycopg", "alembic", "fastapi", "uvicorn", "PIL", "requests", "boto3", "multipart")
               if not _has(m)]
    if missing:
        log.error("Не установлены библиотеки Python: %s", ", ".join(missing))
        log.error("Запустите «Установка.bat» (или: python -m pip install -r requirements.txt) и повторите запуск")
        sys.exit(1)
    # 1. база данных
    try:
        from sqlalchemy import text
        from dreamgoods.db import engine
        with engine.connect() as c:
            c.execute(text("select 1"))
    except Exception as e:
        log.error("Нет подключения к PostgreSQL (%s): %s", config.DATABASE_URL.split("@")[-1], e)
        log.error("Запустите базу: откройте Docker Desktop и выполните docker compose up -d в папке проекта (или «Запуск DreamGoods.bat»)")
        sys.exit(1)
    from alembic import command
    from alembic.config import Config
    acfg = Config(str(config.ROOT / "alembic.ini"))
    acfg.set_main_option("script_location", str(config.ROOT / "migrations"))
    command.upgrade(acfg, "head")
    log.info("Схема базы актуальна")
    # 2. хранилище файлов
    import time
    from dreamgoods.core import storage
    if "--upload-to-s3" in sys.argv:
        storage.upload_local_to_s3()
        return
    for attempt in range(1, 16):   # облачное хранилище может отвечать не сразу
        try:
            storage.ensure_bucket()
            break
        except Exception as e:
            if attempt == 15:
                log.error("Хранилище файлов недоступно (%s): %s", where, e)
                sys.exit(1)
            log.info("Жду хранилище файлов (%s)… попытка %d", where, attempt)
            time.sleep(2)
    checked, missing = storage.audit()
    if missing:
        log.error("❗ В базе есть файлы, которых нет в хранилище (%d из %d проверенных) — картинки не будут показываться.",
                  missing, checked)
        if config.STORAGE != "s3":
            log.error("   Ищу файлы в папке: %s", config.STORAGE_DIR)
            log.error("   Если вы обновляли программу — скопируйте папку data из старой папки в новую и перезапустите.")
    elif checked:
        log.info("Хранилище: файлы на месте (проверено %d)", checked)
    # 3. первый запуск и перенос данных прежней версии
    from sqlalchemy import func, select
    from dreamgoods import db, workers
    from dreamgoods.db.models import Organization, Product
    from dreamgoods.services import legacy, projects
    org_id = projects.bootstrap()
    from dreamgoods.services import presets
    presets.seed(org_id)
    from dreamgoods.services import consents as consents_svc
    consents_svc.seed(org_id)
    from dreamgoods.core import auth
    if "--reset-master" in sys.argv:
        auth.reset_master(org_id)
    auth.bootstrap_master(org_id)
    auth.ensure_master_cabinets(org_id)
    src = None
    if "--import-legacy" in sys.argv:
        src = sys.argv[sys.argv.index("--import-legacy") + 1]
    elif config.app_env("DISABLE_LEGACY_IMPORT", "").strip().lower() not in ("1", "true", "yes", "on"):
        with db.session() as s:
            empty = not s.scalar(select(func.count(Product.id)))
            done = (s.scalars(select(Organization).order_by(Organization.id)).first().settings or {}).get("legacy_imported")
        found = legacy.find_legacy(config.ROOT)
        if empty and found and not done:
            log.info("Найдены данные прежней версии в %s — переношу в базу (один раз)", found)
            src = found
    if src:
        legacy.run(src)
    # 4. очередь и сервер. Сначала проверяем порт: вторая копия без интерфейса не должна разбирать очередь
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":   # Linux: не путать занятый порт с соединениями прошлого запуска (TIME_WAIT)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((config.HOST, config.PORT))
    except OSError:
        log.error("Порт %s:%s занят — DreamGoods уже запущен (или порт занят другой программой). Откройте http://%s:%s",
                  config.HOST, config.PORT, config.HOST, config.PORT)
        sys.exit(1)
    finally:
        probe.close()
    workers.register_instance()
    workers.recover()
    workers.start_workers()
    workers.resume.start()
    import uvicorn
    url = f"http://{config.HOST}:{config.PORT}"
    log.info("DreamGoods запущен: %s  (остановить: Ctrl+C)", url)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    server = uvicorn.Server(uvicorn.Config("dreamgoods.api.app:app", host=config.HOST, port=config.PORT, log_level="warning"))
    if stop_event is not None:
        def shutdown():
            stop_event.wait()
            server.should_exit = True
        threading.Thread(target=shutdown, daemon=True).start()
    try:
        server.run()
    finally:
        if stop_event is not None:
            from dreamgoods.workers.queue import shutdown_workers
            shutdown_workers()
            db.engine.dispose()


if __name__ == "__main__":
    _limit_malloc_arenas()
    main()

