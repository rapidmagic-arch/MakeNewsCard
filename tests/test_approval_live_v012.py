import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from bs4 import BeautifulSoup
import pytest
from meditip.approval_live import approval_url,parse_approval_page,fetch_approval,save_live_approval,ensure_single_approval_mode
from meditip.collect import import_approval_bytes
from meditip.db import connect,setup,ensure_edition,get_edition,edition_rows
from meditip.edition import prepare
from meditip.render import render
from meditip.branding import get_branding,public_branding,save_branding,default_footer,default_banner

ROOT=Path(__file__).resolve().parents[1]
START,END='2026-11-16','2026-11-22'
TEMPLATE=ROOT/'templates/892_slots_original.html'
def fixture(kind):
    return (ROOT/'fixtures'/f'approval_{kind}_20261116_page1.html').read_text(encoding='utf8')

@pytest.mark.parametrize('kind,total,length',[('clinical',34,10),('treatment',4,4),('drug',23,10)])
def test_observed_official_page(kind,total,length):
    n,rows=parse_approval_page(fixture(kind),kind,START,END)
    assert n==total and len(rows)==length
    assert [r['number'] for r in rows]==list(range(1,length+1))
    assert all(r['title'] and r['approved'] and r['stable'] for r in rows)
    assert all(r['within'] or kind=='drug' for r in rows)
    with pytest.raises(ValueError,match='날짜 조건'):
        parse_approval_page(fixture(kind),kind,'2026-11-15',END)

class FakeResponse:
    def __init__(self,url,html):self.url=url;self.content=html.encode('utf8')
    def raise_for_status(self):pass
class FakeSession:
    def __init__(self,pages):self.pages=pages;self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append(url);page=int(parse_qs(urlsplit(url).query)['page'][0])
        return FakeResponse(url,self.pages[page-1])

def test_verified_paging_and_repeated_page():
    soup=BeautifulSoup(fixture('clinical'),'html.parser')
    soup.find('p').string='총 11건'
    first=str(soup)
    tbody=soup.select_one('tbody')
    for row in tbody.select('tr')[1:]:row.decompose()
    td=tbody.select_one('td');td.clear();td.string='11'
    anchor=tbody.select_one('a[href]')
    anchor['href']=anchor['href'].replace('clinicExamSeq=202600934','clinicExamSeq=202699999')
    # Change public receipt/sequence deterministically in the synthetic final page.
    anchor['href']=anchor['href'].replace('receiptNo=20260205728','receiptNo=20269999999')
    second=str(soup)
    session=FakeSession([first,second])
    out=fetch_approval('clinical',START,END,session)
    assert out['total']==11 and out['pages']==2 and len(out['rows'])==11
    assert len(session.calls)==2
    with pytest.raises(ValueError,match='순번'):
        fetch_approval('clinical',START,END,FakeSession([first,first]))
    with pytest.raises(ValueError,match='건수가'):
        fetch_approval('clinical',START,END,FakeSession([first,second.replace('총 11건','총 12건')]))

def test_live_treatment_persistence_and_mixed_mode(tmp_path):
    with connect(tmp_path/'live.db') as con:
        setup(con);ensure_edition(con,'week',START,END)
        ed=get_edition(con,'week')
        result=fetch_approval('treatment',START,END,FakeSession([fixture('treatment')]))
        first=save_live_approval(con,'treatment',ed,result);prepare(con,'week')
        assert first['official_total']==4 and first['records']==4 and first['save_counts']['new']==4
        second=save_live_approval(con,'treatment',ed,result);prepare(con,'week')
        assert second['save_counts']['unchanged']==4 and len(edition_rows(con,'week'))==4
        rows=edition_rows(con,'week')
        assert all(r['verification']=='official_public_list' for r in rows)
        assert all(json.loads(r['original_metadata'])['identity_method']=='public_fields_and_occurrence' for r in rows)
        html=render(con,'week',TEMPLATE,preview=True)
        assert '치료목적 사용승인' in html and '방광암' in html
        with pytest.raises(ValueError,match='혼합'):
            ensure_single_approval_mode(con,'treatment',ed,'csv')
        with pytest.raises(ValueError,match='혼합'):
            import_approval_bytes(con,'제품명,승인일\nTest,2026-11-20\n'.encode(),'treatment',ed)

def test_csv_first_blocks_live_and_default_branding(tmp_path):
    with connect(tmp_path/'csv.db') as con:
        setup(con);ensure_edition(con,'week',START,END)
        ed=get_edition(con,'week')
        import_approval_bytes(con,'제품명,승인일\nTest,2026-11-20\n'.encode(),'treatment',ed)
        with pytest.raises(ValueError,match='혼합'):
            ensure_single_approval_mode(con,'treatment',ed,'live')
        default=get_branding(con)
        assert default['contact_name']=='최서영' and default['email']=='sychoi@meditip.co.kr'
        assert default_footer(TEMPLATE).startswith('data:image/jpeg;base64,')
        assert default_banner(TEMPLATE).startswith('data:image/jpeg;base64,')
        save_branding(con,{'contact_name':'New contact','email':'test@example.org'})
        assert public_branding(con)['contact_name']=='New contact'
        assert public_branding(con)['sample_contact']==default
        save_branding(con,{'contact_name':'','email':''})
        assert get_branding(con)['contact_name']==''
