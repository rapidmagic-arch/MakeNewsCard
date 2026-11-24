"""Template-selection regression: existing layout, Outlook cards, saved snapshot and HTTP."""
import hashlib
import json
import http.client
import re
import socket
import threading
import time
from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from meditip.db import connect, setup, ensure_edition, save_item, edition_rows, get_edition
from meditip.edition import prepare, set_top_order, update_decision
from meditip.render import render
from meditip.mail_templates import TEMPLATES, validate_template_id
from meditip.workflow import confirm, confirmed_html, require_draft
import meditip.server as server

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates'/'892_slots_original.html'

def test_template_edition_and_confirm(tmp_path):
    db=tmp_path/'newsletter.db'
    with connect(db) as con:
        setup(con);ensure_edition(con,'w','2026-11-16','2026-11-22')
        save_item(con,{'source_key':'press','source_group':'mfds','section':'mfds.press',
            'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=100',
            'title':'의약품 안전 안내','published_at':'2026-11-17'})
        save_item(con,{'source_key':'dailypharm','source_group':'industry','section':'industry.policy',
            'url':'https://www.dailypharm.com/user/news/777',
            'title':'약가 제도 개정','published_at':'2026-11-18'})
        con.commit();prepare(con,'w')
        item=next(x for x in edition_rows(con,'w') if x['source_group']=='industry')
        update_decision(con,'w',item['id'],{'include_detail':True,'summary_override':'최종 검토 요약'})
        set_top_order(con,'w',[item['id']])
        assert get_edition(con,'w')['template_id']=='classic'
        assert 'i6sq' in render(con,'w',TEMPLATE,preview=True)
        con.execute("UPDATE editions SET template_id='outlook_cards' WHERE id='w'");con.commit()
    with connect(db) as con:
        preview=render(con,'w',TEMPLATE,preview=True)
        parsed=BeautifulSoup(preview,'html.parser')
        assert '미확정 미리보기' in preview and '최종 검토 요약' in preview
        assert '약가 제도 개정' in preview and '의약품 안전 안내' in preview
        assert parsed.select('td[width="50%"]')
        assert len(parsed.select('table[role="presentation"]'))>=3
        assert '<script' not in preview and '<style' not in preview
        assert 'display:flex' not in preview and 'grid-template-columns' not in preview
        result=confirm(con,'w',TEMPLATE,'담당자','893')
        frozen=confirmed_html(con,'w')
        assert '미확정 미리보기' not in frozen
        assert hashlib.sha256(frozen.encode()).hexdigest()==result['html_sha256']
        assert json.loads(con.execute("SELECT raw_json FROM edition_confirmations WHERE edition_id='w'").fetchone()[0])['edition']['template_id']=='outlook_cards'
        with pytest.raises(ValueError):require_draft(con,'w')
        ensure_edition(con,'next','2026-11-23','2026-11-29')
        assert get_edition(con,'next')['template_id']=='classic'
        con.execute("UPDATE editions SET template_id='classic' WHERE id='w'");con.commit()
        assert confirmed_html(con,'w')==frozen

def test_invalid_template():
    assert list(TEMPLATES)==['classic','outlook_cards']
    with pytest.raises(ValueError):validate_template_id('../file')
    with pytest.raises(ValueError):validate_template_id(None)

def test_migration(tmp_path):
    with connect(tmp_path/'previous.db') as con:
        con.execute('CREATE TABLE editions (id TEXT PRIMARY KEY,period_start TEXT,period_end TEXT,title TEXT,top_target INTEGER,status TEXT,seeded_top INTEGER,created_at TEXT)')
        con.execute("INSERT INTO editions VALUES ('old','2026-11-16','2026-11-22','예전 회차',4,'draft',0,'2026-11-16')")
        con.commit();setup(con);setup(con)
        assert get_edition(con,'old')['template_id']=='classic'

def test_http_template_choice_and_lock(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    path=tmp_path/'issue.db'
    with connect(path) as con:
        setup(con);ensure_edition(con,'week','2026-11-16','2026-11-22')
        save_item(con,{'source_key':'press','source_group':'mfds','section':'mfds.press',
            'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=321',
            'title':'약품 정보','published_at':'2026-11-17'})
        con.commit();prepare(con,'week')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    threading.Thread(target=server.serve,args=(path,TEMPLATE,ROOT/'editor.html','week',port),daemon=True).start()
    def req(method,url,obj=None,token=None):
        con=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'}
        if token:headers['X-Local-Token']=token
        con.request(method,url,json.dumps(obj).encode() if obj is not None else None,headers)
        r=con.getresponse();status=r.status;body=r.read().decode('utf8');ctype=r.getheader('Content-Type');con.close()
        return status,(json.loads(body) if (ctype or '').startswith('application/json') else body)
    for _ in range(100):
        try:
            status,html=req('GET','/')
            if status==200:break
        except OSError:time.sleep(.03)
    assert status==200 and 'id="templateChoice"' in html
    token=re.search(r'name="local-token" content="([^"]+)"',html).group(1)
    assert len(req('GET','/api/templates')[1]['templates'])==2
    assert req('POST','/api/edition/template',{'template_id':'outlook_cards'})[0]==403
    assert req('POST','/api/edition/template',{'template_id':'unknown'},token)[0]==400
    assert req('POST','/api/edition/template',{'template_id':'outlook_cards'},token)[0]==200
    assert req('GET','/api/edition')[1]['edition']['template_id']=='outlook_cards'
    assert '미확정 미리보기' in req('GET','/preview/html')[1]
    assert '편집 초안' in req('GET','/export/html')[1]
    assert req('POST','/api/confirm',{'confirmed_by':'담당자','issue_number':'893','acknowledged':True},token)[0]==200
    assert req('POST','/api/edition/template',{'template_id':'classic'},token)[0]==400
    final=req('GET','/preview/html')[1]
    assert '미확정 미리보기' not in final
    assert req('GET','/export/html')[1]==final
