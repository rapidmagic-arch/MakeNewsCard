"""Localhost HTTP regression for immutable archive and active-edition isolation."""
import http.client
import json
import socket
import threading
import time
from pathlib import Path
from meditip.db import connect, setup, ensure_edition, save_item
from meditip.edition import prepare
from meditip.workflow import confirm
from meditip.server import serve

ROOT=Path(__file__).resolve().parents[1]

def test_library_http_keeps_active_edition(tmp_path):
    path=tmp_path/'test.db'
    with connect(path) as con:
        setup(con)
        ensure_edition(con,'draft-test','2026-11-16','2026-11-22','편집 중')
        ensure_edition(con,'confirmed-test','2026-11-09','2026-11-15','완성 뉴스레터')
        save_item(con,{'source_key':'press','source_group':'mfds','section':'mfds.press',
                       'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=10020',
                       'title':'허가 관련 공식 자료','published_at':'2026-11-10'})
        con.commit();prepare(con,'confirmed-test')
        confirm(con,'confirmed-test',ROOT/'templates'/'892_slots_original.html','검증자','999')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    threading.Thread(target=serve,args=(path,ROOT/'templates/892_slots_original.html',ROOT/'editor.html','draft-test',port),daemon=True).start()

    def get(path):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        conn.request('GET',path,headers={'Host':f'127.0.0.1:{port}'})
        res=conn.getresponse();data=res.read();headers=dict(res.getheaders());status=res.status;conn.close()
        return status,headers,data

    for _ in range(100):
        try:
            status,_,_=get('/api/library')
            if status==200:break
        except OSError:time.sleep(.03)
    assert status==200
    code,_,body=get('/api/library?status=confirmed&page=1')
    assert code==200
    payload=json.loads(body)
    assert payload['total']==1 and payload['items'][0]['id']=='confirmed-test'
    code,headers,html=get('/api/library/html?edition_id=confirmed-test')
    assert code==200 and b'html' in html.lower()
    assert 'Content-Disposition' not in headers
    code,headers,download=get('/api/library/html?edition_id=confirmed-test&download=1')
    assert code==200 and 'attachment' in headers['Content-Disposition'] and download==html
    assert get('/api/library/html?edition_id=draft-test')[0]==404
    assert get('/api/library?status=unknown')[0]==400
    assert get('/api/library?page=-1')[0]==400
    assert json.loads(get('/api/edition')[2])['edition']['id']=='draft-test'
