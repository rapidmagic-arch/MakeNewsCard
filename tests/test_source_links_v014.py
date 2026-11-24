import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from bs4 import BeautifulSoup
import pytest
from meditip.source_links import resolve_source_link,approval_search_url
from meditip.approval_live import parse_approval_page
from meditip.db import connect,setup,ensure_edition,edition_rows
from meditip.collect import import_approval_bytes
from meditip.edition import prepare
from meditip.render import render
from meditip.workflow import confirm,confirmed_html

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates/892_slots_original.html'
START,END='2026-11-16','2026-11-22'

def query(url):return parse_qs(urlsplit(url).query)

@pytest.mark.parametrize('kind',['clinical','treatment','drug'])
def test_actual_public_fixture_links(kind):
    html=(ROOT/'fixtures'/f'approval_{kind}_20261116_page1.html').read_text(encoding='utf8')
    _,rows=parse_approval_page(html,kind,START,END)
    first=rows[0]
    row=dict(source_key='official_live_'+kind,source_group=kind,title=first['title'],
             published_at=first['approved'],url=approval_search_url(kind,START,END),
             original_metadata=json.dumps({'approval_row':first['raw'],'source_url':first['href']}))
    url,mode=resolve_source_link(row)
    if kind in ('clinical','drug'):
        assert mode=='detail' and url==first['href']
    else:
        assert mode=='search'
        assert query(url)['prductName']==[first['raw']['제품명']]
        assert query(url)['applyEntpName']==[first['raw']['신청인']]
        assert query(url)['approvalDtStart']==query(url)['approvalDtEnd']==[first['approved']]
    # Reject unrelated metadata URLs, fall back to official search.
    row['original_metadata']=json.dumps({'approval_row':first['raw'],'source_url':'https://evil.example/anything'})
    url,mode=resolve_source_link(row)
    assert mode=='search' and urlsplit(url).hostname=='nedrug.mfds.go.kr'

def test_original_url_and_csv_search_encoding():
    row=dict(source_key='medicaltimes',source_group='industry',url='https://www.medicaltimes.com/Main/News/NewsView.html?ID=1172075')
    assert resolve_source_link(row)==(row['url'],'detail')
    assert not resolve_source_link({**row,'url':'javascript:alert(1)'})[0]
    row=dict(source_key='official_csv_clinical',source_group='clinical',title='원본 제목 & A+B',
             title_override='편집된 제목',published_at='2026-11-20',
             url='https://nedrug.mfds.go.kr/searchClinic',original_metadata='{}')
    url,mode=resolve_source_link(row)
    assert mode=='search' and query(url)['searchKeyword']==['원본 제목 & A+B']
    assert query(url)['searchType']==['ST3']
    assert resolve_source_link({**row,'published_at':None})==('https://nedrug.mfds.go.kr/searchClinic','source')

def test_both_templates_and_snapshot(tmp_path):
    with connect(tmp_path/'links.db') as con:
        setup(con);ensure_edition(con,'week',START,END)
        from meditip.db import get_edition
        ed=get_edition(con,'week')
        for kind,data in [('clinical','임상시험제목,제품명,승인일\nTrial-A,SRP-9001,2026-11-20\n'),
                          ('treatment','제품명,신청인,승인일\nDrug & A,Hospital+B,2026-11-20\n'),
                          ('drug','품목명,업체명,허가일자\nDrug-B,Maker & Co,2026-11-20\n')]:
            assert import_approval_bytes(con,data.encode(),kind,ed)['imported']==1
        prepare(con,'week')
        rows=edition_rows(con,'week')
        original={r['id']:r['url'] for r in rows}
        links={resolve_source_link(r)[0] for r in rows}
        weekly={approval_search_url(k,START,END) for k in ('clinical','treatment','drug')}
        for mode in ('classic','outlook_cards'):
            soup=BeautifulSoup(render(con,'week',TEMPLATE,preview=True,template_id=mode),'html.parser')
            urls={a['href'] for a in soup.select('a[href]')}
            assert links<=urls and weekly<=urls
        confirm(con,'week',TEMPLATE,'tester','998')
        frozen=confirmed_html(con,'week')
        assert all(original[r['id']]==r['url'] for r in edition_rows(con,'week'))
        assert links<={a['href'] for a in BeautifulSoup(frozen,'html.parser').select('a[href]')}
