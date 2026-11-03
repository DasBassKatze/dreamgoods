"""Frozen entry point. Own database only; no Docker, services or elevated privileges."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=kwargs.pop("check", True), capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=kwargs.pop('cwd', str(Path(command[0]).parent)),
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, **kwargs)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='replace')
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--postgres-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    root = args.data_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # A second backend must never recover the queue or operate on the same database.
    lock = (root / 'backend.lock').open('a+b')
    if os.name == 'nt':
        import msvcrt
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    pgroot = root
    pg = args.postgres_dir.resolve() / 'bin'
    ext = '.exe' if os.name == 'nt' else ''
    ctl = pg / ('pg_ctl' + ext)
    cluster = pgroot / 'postgres'
    credentials = root / 'database.json'
    if credentials.exists():
        password = json.loads(credentials.read_text())['password']
    else:
        if (cluster / 'PG_VERSION').exists():
            raise RuntimeError('database.json отсутствует. Восстановите его из резервной копии; база сохранена.')
        password = secrets.token_hex(24)
        credentials.write_text(json.dumps({'password': password}))
        credentials.chmod(0o600)
    if (cluster / 'PG_VERSION').exists() and (cluster / 'PG_VERSION').read_text().strip() != '17':
        raise RuntimeError('Несовместимая версия PostgreSQL. Требуется перенос базы; файлы сохранены.')
    if not (cluster / 'PG_VERSION').exists():
        pwfile = pgroot / 'init-password.tmp'
        try:
            pwfile.write_text(password)
            run([pg / ('initdb' + ext), '-D', cluster, '-U', 'dreamgoods',
                 '--auth-host=scram-sha-256', '--auth-local=scram-sha-256',
                 '--encoding=UTF8', '--locale=C', '--pwfile', pwfile])
        finally:
            pwfile.unlink(missing_ok=True)
    # If an earlier GUI crashed, stop only this private cluster before restart.
    if (cluster / 'postmaster.pid').exists() and run([ctl, '-D', cluster, 'status'], check=False).returncode == 0:
        run([ctl, '-D', cluster, '-m', 'fast', '-w', 'stop'])
    dbport = free_port()
    while dbport == args.port:
        dbport = free_port()
    env = dict(os.environ, PGPASSWORD=password, PGCONNECT_TIMEOUT='5')
    started = False
    try:
        run([ctl, '-D', cluster, '-l', pgroot / 'postgres.log', '-o',
             f'-h 127.0.0.1 -p {dbport}', '-w', '-t', '60', 'start'])
        started = True
        exists = run([pg / ('psql' + ext), '-h', '127.0.0.1', '-p', str(dbport), '-U', 'dreamgoods',
                      '-d', 'postgres', '-tAc', "SELECT 1 FROM pg_database WHERE datname='dreamgoods'"], env=env)
        if exists.stdout.strip() != '1':
            run([pg / ('createdb' + ext), '-h', '127.0.0.1', '-p', str(dbport), '-U', 'dreamgoods', 'dreamgoods'], env=env)
        # Configure BEFORE importing any DreamGoods module (config is evaluated at import).
        os.environ.update({
            'DATABASE_URL': f'postgresql+psycopg://dreamgoods:{password}@127.0.0.1:{dbport}/dreamgoods',
            'DREAMGOODS_HOST': '127.0.0.1', 'DREAMGOODS_PORT': str(args.port),
            'DREAMGOODS_LOG_DIR': str(root / 'logs'), 'DREAMGOODS_EXPORT_DIR': str(root / 'exports'),
            'DREAMGOODS_DISABLE_LEGACY_IMPORT': 'true', 'STORAGE': 'local', 'STORAGE_DIR': str(root / 'files'),
        })
        stop = threading.Event()
        def watch_parent():
            # EOF also handles a crashed/killed Electron parent.
            sys.stdin.readline()
            stop.set()
        threading.Thread(target=watch_parent, daemon=True).start()
        sys.argv = [sys.argv[0], '--no-browser']
        import run_dreamgoods
        run_dreamgoods.main(stop_event=stop)
    finally:
        if started:
            run([ctl, '-D', cluster, '-m', 'fast', '-w', '-t', '60', 'stop'])
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        exc = sys.exception()
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stdout, exc.stderr, file=sys.stderr)
        sys.exit(1)
