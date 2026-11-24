from pathlib import Path
import base64
import pytest
from meditip.managed_files import ManagedFiles,workspace_for_db,edition_folder
from meditip.db import connect,setup
from meditip.branding import save_branding,get_branding,default_banner

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates/892_slots_original.html'

def test_portable_directories_and_byte_identity(tmp_path):
    db=tmp_path/'data'/'newsletter.db'
    assert workspace_for_db(db)==tmp_path
    assert workspace_for_db(tmp_path/'custom.db')==tmp_path
    store=ManagedFiles(tmp_path)
    for d in ('branding/defaults','branding/custom','imports','exports'):
        assert (store.root/d).is_dir()
    csv='제품명,승인일\r\n테스트,2026-11-20\r\n'.encode('cp949')
    one=store.import_file('week','approval/drug','../../원본.csv',csv,'.csv')
    assert (store.root/one).read_bytes()==csv
    assert store.import_file('week','approval/drug','원본.csv',csv,'.csv')==one
    two=store.import_file('week','approval/drug','원본.csv',csv+b'\r\n','.csv')
    assert one!=two and (store.root/one).read_bytes()==csv
    assert edition_folder('A/B')!=edition_folder('A_B')
    assert store.export_file('week','confirmed','newsletter','<p>테스트</p>','.html')==store.export_file('week','confirmed','newsletter','<p>테스트</p>','.html')
    with pytest.raises(ValueError):store.save('../escape','x',b'x','.json')
    with pytest.raises(ValueError):store.save('imports','x',b'x','.exe')

def test_brand_copies_keep_database_authority_and_previous_versions(tmp_path):
    managed=ManagedFiles(tmp_path)
    data=default_banner(TEMPLATE)
    raw=base64.b64decode(data.split(',',1)[1])
    with connect(tmp_path/'data'/'newsletter.db') as con:
        setup(con)
        save_branding(con,{'banner':data},managed)
        images=list((managed.root/'branding'/'custom'/'banner').glob('*.jpg'))
        assert len(images)==1 and images[0].read_bytes()==raw
        assert get_branding(con)['banner']==data
        save_branding(con,{'banner':''},managed)
        assert not get_branding(con).get('banner')
        assert images[0].read_bytes()==raw
