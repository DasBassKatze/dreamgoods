"""Build smoke: exercise Unicode data paths before spending time packaging the installer."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
repo = Path(__file__).resolve().parent.parent
root = Path(tempfile.mkdtemp(prefix='DreamGoods-проверка '))
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
with (root/'smoke-backend.log').open('w',encoding='utf-8') as log:
    child = subprocess.Popen([sys.executable,str(repo/'desktop/backend.py'),'--data-dir',str(root),
        '--postgres-dir',str(repo/'desktop/vendor/postgresql'),'--port',str(port)],stdin=subprocess.PIPE,stdout=log,stderr=log,
        env=dict(os.environ,PYTHONPATH=str(repo),PYTHONIOENCODING='utf-8'))
    try:
        until=time.monotonic()+90
        while True:
            if child.poll() is not None: raise RuntimeError('Backend exited before health check')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1) as response:
                    if response.status==200: break
            except OSError:
                pass
            if time.monotonic()>until: raise RuntimeError('Backend startup timed out')
            time.sleep(.2)
    except Exception:
        log.flush();print((root/'smoke-backend.log').read_text(encoding='utf-8',errors='replace'));raise
    finally:
        if child.poll() is None:
            child.stdin.close()
            try: child.wait(timeout=90)
            except subprocess.TimeoutExpired: child.kill();child.wait()
if child.returncode: raise RuntimeError((root/'smoke-backend.log').read_text(encoding='utf-8',errors='replace'))
if (root/'postgres/postmaster.pid').exists(): raise RuntimeError('PostgreSQL did not stop')
print('PASS: Unicode data path, PostgreSQL init, migrations, bootstrap, health, clean shutdown')
