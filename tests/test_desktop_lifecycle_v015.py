import re
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import requests

from meditip.db import connect,setup,ensure_edition
from meditip.lifecycle import DesktopLifecycle
import meditip.server as server

ROOT=Path(__file__).resolve().parents[1]

def test_tray_exit_lifecycle_blocks_active_requests_and_jobs():
    life=DesktopLifecycle()
    stopped=threading.Event()
    busy={'value':True}
    life.bind(SimpleNamespace(shutdown=stopped.set),lambda:busy['value'])
    assert not life.request_stop()
    busy['value']=False
    assert life.enter()
    assert not life.request_stop()
    life.leave()
    assert life.request_stop()
    assert stopped.wait(2)
    assert not life.enter()
    assert life.request_stop()

def test_live_server_shutdown_refuses_collection_then_releases_port(tmp_path,monkeypatch):
    started=threading.Event()
    release=threading.Event()
    def mock_collect(*args,**kwargs):
        started.set()
        if not release.wait(8):raise RuntimeError('mock collection timeout')
        return dict(source='press',status='success',pages=1,records=0,item_ids=[])
    monkeypatch.setattr(server,'collect_source',mock_collect)
    db=tmp_path/'data'/'newsletter.db'
    with connect(db) as con:
        setup(con);ensure_edition(con,'week','2026-11-16','2026-11-22')
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    life=DesktopLifecycle()
    def worker():
        try:server.serve(db,ROOT/'templates/892_slots_original.html',ROOT/'editor.html','week',port,lifecycle=life)
        except Exception as exc:life.complete(exc)
        else:life.complete()
    thread=threading.Thread(target=worker,daemon=True)
    thread.start()
    assert life.ready.wait(5) and life.error is None
    base=f'http://127.0.0.1:{port}'
    session=requests.Session()
    try:
        html=session.get(base,timeout=3).text
        token=re.search(r'name="local-token" content="([^"]+)"',html).group(1)
        headers={'X-Local-Token':token}
        assert session.post(base+'/api/app/shutdown',json={},timeout=3).status_code==403
        res=session.post(base+'/api/collect',json=dict(sources=['press'],start='2026-11-16',end='2026-11-22',method='board',max_pages=1),headers=headers,timeout=3)
        assert res.status_code==202 and started.wait(3)
        assert not life.request_stop()
        assert session.post(base+'/api/app/shutdown',json={},headers=headers,timeout=3).status_code==409
        release.set()
        for _ in range(100):
            if life.request_stop():break
            time.sleep(.05)
        else:raise AssertionError('finished collection did not permit shutdown')
        assert life.finished.wait(5)
        assert life.error is None
        thread.join(1)
        assert not thread.is_alive()
        with socket.socket() as probe:
            probe.settimeout(.5)
            assert probe.connect_ex(('127.0.0.1',port))!=0
        # Previously saved database remains usable.
        with connect(db) as con:assert con.execute('SELECT COUNT(*) FROM editions').fetchone()[0]==1
    finally:
        release.set()
        if not life.finished.is_set():
            for _ in range(100):
                if life.request_stop():break
                time.sleep(.05)
        thread.join(5)
        session.close()
