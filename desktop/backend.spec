# Run from repository root: pyinstaller --noconfirm desktop/backend.spec
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from pathlib import Path
root = Path(SPECPATH).parent
hidden = collect_submodules('dreamgoods') + collect_submodules('uvicorn') + collect_submodules('psycopg')
a = Analysis([str(root / 'desktop/backend.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root / 'migrations'), 'migrations'), (str(root / 'alembic.ini'), '.'),
                        (str(root / 'dreamgoods/web'), 'dreamgoods/web')],
    hiddenimports=hidden + ['run_dreamgoods'], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter', 'PyQt5', 'PyQt6'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DreamGoodsBackend', console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DreamGoodsBackend')
