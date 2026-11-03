# Run from repository root: pyinstaller --noconfirm desktop/backend.spec
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from pathlib import Path
root = Path(SPECPATH).parent
# api/ and its routers are PEP 420 namespace packages; pkgutil-based collection
# skips them. List repository modules explicitly, including those imported by URL.
hidden = ['.'.join(p.relative_to(root).with_suffix('').parts) for p in (root / 'dreamgoods').rglob('*.py')
          if p.name != '__init__.py']
hidden += collect_submodules('uvicorn') + collect_submodules('psycopg')
a = Analysis([str(root / 'desktop/backend.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root / 'migrations'), 'migrations'), (str(root / 'alembic.ini'), '.'),
                        (str(root / 'dreamgoods/web'), 'dreamgoods/web')],
    hiddenimports=hidden + ['run_dreamgoods'], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter', 'PyQt5', 'PyQt6'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DreamGoodsBackend', console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DreamGoodsBackend')
