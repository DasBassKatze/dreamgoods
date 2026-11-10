import io
import zipfile

from PIL import Image
from dreamgoods import db
from dreamgoods.core import storage
from dreamgoods.db.models import Frame, Generation
from dreamgoods.services import export


def test_checked_and_manual_exports_exclude_unchecked_and_preserve_legacy(database, monkeypatch, tmp_path):
    _, ids = database
    monkeypatch.setattr(storage.config, 'STORAGE_DIR', tmp_path / 'files')
    monkeypatch.setattr(storage.config, 'STORAGE', 'local')
    monkeypatch.setattr(export.config, 'EXPORT_DIR', tmp_path / 'exports')
    image = io.BytesIO(); Image.new('RGB', (32, 32), 'white').save(image, format='PNG')
    with db.session() as s:
        asset = storage.put(s, ids['org'], image.getvalue(), 'output', 'test.png')
        for position, status in enumerate(['pass', 'accepted', 'unchecked', 'review', 'rejected'], 1):
            f = s.get(Frame, ids['frame']) if position == 1 else Frame(product_id=ids['product'], position=position, prompt='photo')
            f.status = status; s.add(f); s.flush()
            g = Generation(frame_id=f.id, output_asset_id=asset.id, status='ok')
            s.add(g); s.flush(); f.current_generation_id = g.id
    for include, expected in [('checked', {'01.png', '02.png'}), ('manual', {'02.png'}),
                              ('accepted', {'01.png', '02.png', '03.png'}), ('all', {'01.png', '02.png', '03.png', '04.png', '05.png'})]:
        path, count = export.export_zip(ids['project'], include)
        with zipfile.ZipFile(path) as z:
            names = {p.rsplit('/', 1)[-1] for p in z.namelist() if p.endswith('.png')}
            assert names == expected and count == len(expected)
            report = z.read('report.csv').decode('utf-8-sig')
            assert 'без проверки' in report or 'unchecked' in report or include in ('manual', 'checked')
        path.unlink()
