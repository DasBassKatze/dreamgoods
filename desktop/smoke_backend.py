"""Build smoke: exercise Unicode data paths before spending time packaging the installer."""
import os
import json
import http.cookiejar
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
entry = [str(repo/'dist/DreamGoodsBackend/DreamGoodsBackend.exe')] if '--frozen' in sys.argv else [sys.executable,str(repo/'desktop/backend.py')]
with (root/'smoke-backend.log').open('w',encoding='utf-8') as log:
    child = subprocess.Popen(entry+['--data-dir',str(root),
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
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/auth/login',data=json.dumps({'email':'admin','password':'admin'}).encode(),headers={'Content-Type':'application/json'})
        with opener.open(request,timeout=10) as response: assert response.status==200
        with opener.open(f'http://127.0.0.1:{port}/api/projects',timeout=10) as response:
            assert json.load(response)['projects'], 'No initial projects'
    except Exception as error:
        if isinstance(error,urllib.error.HTTPError): print(error.read().decode('utf-8','replace'))
        log.flush()
        for name in ('smoke-backend.log','postgres.log'):
            if (root/name).exists(): print((root/name).read_text(encoding='utf-8',errors='replace'))
        raise
    finally:
        if child.poll() is None:
            child.stdin.close()
            try: child.wait(timeout=90)
            except subprocess.TimeoutExpired: child.kill();child.wait()
if child.returncode: raise RuntimeError((root/'smoke-backend.log').read_text(encoding='utf-8',errors='replace'))
if (root/'postgres/postmaster.pid').exists(): raise RuntimeError('PostgreSQL did not stop')
print('PASS: Unicode data path, PostgreSQL init, migrations, bootstrap, health, clean shutdown')
