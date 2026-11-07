import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from desktop.data_safety import mark_version, prepare_upgrade


def test_upgrade_creates_verified_checkpoint_once_per_version(tmp_path):
    calls=[]
    def run(args, **kwargs):
        calls.append(args)
        if '--file' in args: Path(args[args.index('--file')+1]).write_bytes(b'PGDMP test')
        return SimpleNamespace(returncode=0)
    mark_version(tmp_path,'0.11.1')
    dump=prepare_upgrade(tmp_path,tmp_path/'pg',1234,{'PGPASSWORD':'secret'},'0.12.0',True,run)
    assert dump.read_bytes().startswith(b'PGDMP')
    assert any('--list' in args for args in calls)
    manifest=json.loads(dump.with_name('manifest.json').read_text())
    assert manifest['from_version']=='0.11.1' and manifest['to_version']=='0.12.0'
    assert 'secret' not in dump.with_name('manifest.json').read_text()
    assert json.loads((tmp_path/'application.json').read_text())['version']=='0.11.1'
    mark_version(tmp_path,'0.12.0')
    assert prepare_upgrade(tmp_path,tmp_path,1234,{},'0.12.0',True,run) is None
    assert len(list((tmp_path/'backups').glob('*/database.dump')))==1
    with pytest.raises(RuntimeError,match='более новую'):
        prepare_upgrade(tmp_path,tmp_path,1234,{},'0.11.1',True,run)


def test_new_install_and_legacy_database_and_backup_failure(tmp_path):
    calls=[]
    def broken(*args,**kwargs): calls.append(1);raise OSError('disk full')
    assert prepare_upgrade(tmp_path,tmp_path,1234,{},'0.12.0',False,broken) is None
    assert not calls
    (tmp_path/'database.json').write_text('{"password":"keep"}')
    with pytest.raises(RuntimeError,match='исходные данные сохранены'):
        prepare_upgrade(tmp_path,tmp_path,1234,{},'0.12.0',True,broken)
    assert (tmp_path/'database.json').read_text()=='{"password":"keep"}'
    assert not (tmp_path/'application.json').exists()
    assert not list((tmp_path/'backups').glob('*/database.dump'))
