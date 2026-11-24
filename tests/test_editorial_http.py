import http.client
import json
import re
import socket
import threading
import time
from pathlib import Path

from meditip.db import connect, setup, save_item, ensure_edition
from meditip.server import serve

ROOT=Path(__file__).resolve().parents[1]

def test_http_ai_export_import_bulk(tmp_path):
    db=tmp_path/'test.db'
    with connect(db) as c:
        setup(c)
        ensure_edition(c,'week','2026-11-16','2026-11-22')
        for i,title in enumerate(['GLP-1 시장 성장','ADC 신약 임상 연구']):
            save_item(c,{'source_group':'industry','source_key':'dailypharm',
                         'section':'industry.unclassified',
                         'url':f'https://www.dailypharm.com/user/news/{70000+i}',
                         'title':title,'published_at':'2026-11-17'})
        c.commit()
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    threading.Thread(target=serve,args=(db,ROOT/'templates'/'892_slots_original.html',ROOT/'editor.html','week',port),daemon=True).start()

    def req(method,path,payload=None,token=None):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'}
        if token:headers['X-Local-Token']=token
        c.request(method,path,body=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        r=c.getresponse(); code,content=r.status,r.read().decode();c.close()
        return code, content

    for _ in range(20):
        try:
            code,html=req('GET','/')
            if code==200:break
        except ConnectionError:time.sleep(.1)
    else:raise AssertionError('server unavailable')
    token=re.search(r'name="local-token" content="([^"]+)"',html).group(1)
    code,content=req('GET','/export/ai')
    assert code==200
    ai=json.loads(content)
    assert len(ai['items'])==2
    code,content=req('GET','/api/edition')
    assert all(x['rule_section'] and x['rule_recommended'] for x in json.loads(content)['items'])
    item=ai['items'][0]
    ai_result={'items':[{'id':item['id'],'score':85,'summary':'내용을 확인해야 하는 AI 제안','section':'industry.global','recommended':True,'reason':'외부 분석 제안'}]}
    assert req('POST','/api/ai/import',ai_result)[0]==403
    import base64
    original=('\ufeff'+json.dumps(ai_result,ensure_ascii=False,indent=4)+'\r\n').encode('utf8')
    code,content=req('POST','/api/ai/import',{'filename':'원본.json','content':base64.b64encode(original).decode()},token)
    assert code==200 and json.loads(content)['analysed']==1
    root=tmp_path/'files'
    assert (root/json.loads(content)['managed_file']).read_bytes()==original
    assert list((root/'exports').rglob('candidates-*.json'))
    code,content=req('GET','/api/edition')
    rows=json.loads(content)['items'];assert not any(x['include_detail'] for x in rows)
    code,content=req('POST','/api/industry/bulk',{'mode':'apply_recommended','ids':[item['id']]},token)
    assert code==200 and json.loads(content)['updated']==1
    code,content=req('GET','/api/edition')
    assert sum(x['include_detail'] for x in json.loads(content)['items'])==1
    code,content=req('GET','/export/html')
    assert code==200 and item['title'] in content
    saved=list((root/'exports').rglob('newsletter-*.html'))
    assert len(saved)==1 and saved[0].read_bytes()==content.encode('utf8')
    assert req('GET','/export/html')[0]==200
    assert len(list((root/'exports').rglob('newsletter-*.html')))==1
