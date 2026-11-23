"""API tests for edition selection, explicit confirmation and locked exports."""
import http.client
import json
import re
import socket
import threading
import time
from pathlib import Path

from meditip.db import connect, setup, ensure_edition, save_item
from meditip.edition import prepare
import meditip.server as server

ROOT=Path(__file__).resolve().parents[1]


def test_live_http_workflow(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    path=tmp_path/'issue.db'
    with connect(path) as con:
        setup(con)
        ensure_edition(con,'week','2026-11-16','2026-11-22')
        save_item(con,{'source_key':'press','source_group':'mfds','section':'mfds.press',
             'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=1001','title':'식약처 자료',
             'published_at':'2026-11-17'})
        con.commit();prepare(con,'week')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    threading.Thread(target=server.serve,args=(path,ROOT/'templates/892_slots_original.html',ROOT/'editor.html','week',port),daemon=True).start()

    def request(method,url,obj=None,token=None):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=4)
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'}
        if token:headers['X-Local-Token']=token
        conn.request(method,url,body=json.dumps(obj).encode() if obj is not None else None,headers=headers)
        resp=conn.getresponse();status=resp.status;body=resp.read().decode('utf8');conn.close()
        if resp.getheader('Content-Type','').startswith('application/json'):
            body=json.loads(body)
        return status,body

    for _ in range(100):
        try:
            status,html=request('GET','/')
            if status==200:break
        except OSError:time.sleep(.03)
    assert status==200
    token=re.search(r"const TOKEN='([^']+)'",html).group(1)
    status,e=request('GET','/api/edition')
    assert status==200 and e['week_label']=='2026-W47' and e['edition']['status']=='draft'
    status,settings=request('GET','/api/settings')
    assert status==200 and not settings['ai_api_available']
    assert request('POST','/api/confirm',{'confirmed_by':'담당자','acknowledged':True})[0]==403
    assert request('POST','/api/ai/review',{'ids':[]},token)[0]==400
    assert request('POST','/api/confirm',{'confirmed_by':'담당자','issue_number':'893','acknowledged':False},token)[0]==400
    status,result=request('POST','/api/confirm',{'confirmed_by':'담당자','issue_number':'893','acknowledged':True},token)
    assert status==200 and result['status']=='confirmed'
    assert request('POST','/api/decision',{'item_id':'unknown','changes':{}},token)[0]==400
    assert request('POST','/api/target',{'count':10},token)[0]==400
    status,final=request('GET','/export/html')
    assert status==200 and '[검토용]' not in final and '확인된 수록 자료 없음' not in final
    assert request('GET','/export/snapshot')[0]==200
    assert request('POST','/api/collect',{'sources':['press'],'start':'2026-11-16','end':'2026-11-22','method':'board','max_pages':1},token)[0]==400
    # New issue can coexist with same source week and does not inherit confirmation.
    status,new=request('POST','/api/edition/new',{'start':'2026-11-16','end':'2026-11-22',
        'edition_id':'special-2026','title':'특별호'},token)
    assert status==200 and new['edition_id']=='special-2026'
    status,info=request('GET','/api/edition')
    assert info['edition']['status']=='draft'
    assert info['edition']['period_start']=='2026-11-16'
    status,back=request('POST','/api/edition/select',{'edition_id':'week'},token)
    assert status==200 and back['edition_id']=='week'
    assert request('GET','/api/edition')[1]['edition']['status']=='confirmed'
