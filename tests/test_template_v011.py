import base64
import hashlib
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from meditip.db import connect, setup, ensure_edition, save_item, edition_rows, get_edition
from meditip.edition import prepare, update_decision, set_top_order
from meditip.company import register_company, company_output_rows, set_company_order
from meditip.collect import import_approval_bytes
from meditip.branding import save_branding, default_banner
from meditip.render import render
from meditip.workflow import confirm, confirmed_html

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates/892_slots_original.html'

def seed(con):
    setup(con)
    ensure_edition(con,'week','2026-11-16','2026-11-22')
    iid=save_item(con,dict(source_key='medicaltimes',source_group='industry',section='industry.unclassified',
        title='Industry unique title',url='https://www.medicaltimes.com/Main/News/View.html?ID=900001',
        published_at='2026-11-17'))
    con.commit()
    prepare(con,'week')
    return iid

def test_company_independent_order_and_identity(tmp_path):
    with connect(tmp_path/'one.db') as con:
        media=seed(con)
        payload=dict(title='Company original',publisher='회사 제공 자료',url='https://example.org/news/1',
                     published_at='2026-11-18',summary='Company approved text')
        manual=register_company(con,'week',payload)
        with pytest.raises(ValueError):register_company(con,'week',{**payload,'url':payload['url']+'?utm_source=test'})
        with pytest.raises(ValueError):register_company(con,'week',{**payload,'url':'https://example.org/news/2','published_at':'2026-11-30'})
        update_decision(con,'week',media,{'company_selected':True})
        set_company_order(con,'week',[media,manual])
        rows=edition_rows(con,'week')
        assert len(rows)==2
        assert [x['id'] for x in company_output_rows(rows)]==[media,manual]
        assert next(x for x in rows if x['id']==media)['include_detail']==0
        update_decision(con,'week',manual,{'include_detail':False})
        assert [x['id'] for x in company_output_rows(edition_rows(con,'week'))]==[media]
        with pytest.raises(ValueError):set_company_order(con,'week',[media,media])
        final=confirm(con,'week',TEMPLATE,'test','901','2026-11-25')
        assert final['status']=='confirmed'
        html=confirmed_html(con,'week')
        assert 'Industry unique title' in html and 'Company original' not in html
        assert '발행일 2026-11-25' in html
        with pytest.raises(ValueError):register_company(con,'week',{**payload,'url':'https://example.org/new'})
        with pytest.raises(ValueError):set_company_order(con,'week',[media,manual])

def test_approval_slots_company_and_banner(tmp_path):
    with connect(tmp_path/'two.db') as con:
        iid=seed(con)
        update_decision(con,'week',iid,{'include_detail':True,'section_override':'industry.policy'})
        set_top_order(con,'week',[iid])
        register_company(con,'week',dict(title='Standalone company news',publisher='공개 언론사',url='https://example.org/company',
                                         published_at='2026-11-18',summary='Company card summary'))
        ed=get_edition(con,'week')
        samples={
          'clinical':'임상시험제목,제품명,의뢰자,임상시험 단계,승인일\nClinical-A,Trial-A,Sponsor-A,3상,2026-11-18\nOutside,Outside,Outside,3상,2026-11-30\n',
          'treatment':'제품명,신청인,대상질환,승인일\nTreatment-A,Applicant-A,Disease-A,2026-11-19\n',
          'drug':'품목명,업체명,허가일자\nDrug-A,Maker-A,2026-11-20\n',
        }
        for kind,content in samples.items():
            raw=content.encode('cp949' if kind=='drug' else 'utf-8-sig')
            assert import_approval_bytes(con,raw,kind,ed)['imported']==1
            again=import_approval_bytes(con,raw,kind,ed)
            assert again['imported']==1
            assert len(again['skipped'])==(1 if kind=='clinical' else 0)
        prepare(con,'week')
        assert len(edition_rows(con,'week'))==5
        assert con.execute("SELECT COUNT(*) FROM runs WHERE edition_id='week'").fetchone()[0]==6
        con.execute("UPDATE editions SET issue_number='902',publication_date='2026-11-25' WHERE id='week'")
        con.commit()
        save_branding(con,dict(contact_name='Test Contact',email='test@example.org',phone='02-0000-0000',website='https://example.org',address='Test address'))
        for mode in ('classic','outlook_cards'):
            html=render(con,'week',TEMPLATE,preview=True,template_id=mode)
            assert all(x in html for x in ('Clinical-A','Treatment-A','Drug-A','2026-11-20','Standalone company news','Test Contact','발행일 2026-11-25','메디칼타임즈'))
            assert 'Outside' not in html
            assert '2026.11.17' not in html
            if mode=='classic':
                soup=BeautifulSoup(html,'html.parser')
                assert soup.select_one('[data-approval-slot="clinical"]').find('table')
                assert 'Treatment-A' in soup.select_one('[data-approval-slot="clinical"]').get_text()
                assert 'Drug-A' in soup.select_one('[data-approval-slot="drug"]').get_text()
                assert 'Standalone company news' in soup.select_one('[data-slot="company_news"]').get_text()
                assert soup.select_one('[data-image-slot="banner"] img')['src']==default_banner(TEMPLATE)
                raw=base64.b64decode(soup.select_one('[data-image-slot="banner"] img')['src'].split(',')[1])
                assert hashlib.sha256(raw).hexdigest()=='eeb891e487f66907b1a74e200805696b9b17390b6524c7637f84b9506baf13df'
                assert '제약 제약' not in soup.get_text()
                assert any('approvalDtStart=2026-11-16' in a['href'] and 'approvalDtEnd=2026-11-22' in a['href'] for a in soup.select('a[href]') if '임상시험승인현황' in a.get_text())
                assert any('sPermitDateStart=2026-11-16' in a['href'] and 'sPermitDateEnd=2026-11-22' in a['href'] for a in soup.select('a[href]') if '주간허가현황' in a.get_text())
        confirm(con,'week',TEMPLATE,'test','902')
        frozen=confirmed_html(con,'week')
        save_branding(con,dict(contact_name='Different contact'))
        assert confirmed_html(con,'week')==frozen
        snap=json.loads(con.execute("SELECT raw_json FROM edition_confirmations WHERE edition_id='week'").fetchone()[0])
        assert snap['edition']['publication_date']=='2026-11-25'

def test_branding_rejects_invalid_image_and_url(tmp_path):
    with connect(tmp_path/'three.db') as con:
        setup(con)
        for obj in ({'website':'javascript:alert(1)'},{'email':'bad'},{'banner':'data:image/svg+xml;base64,AAAA'},
                    {'banner':'data:image/jpeg;base64,AAAA'}):
            with pytest.raises(ValueError):save_branding(con,obj)
        source=default_banner(TEMPLATE)
        out=save_branding(con,{'logo':source,'banner':source})
        assert out['logo_custom'] and out['banner_custom']
        assert not save_branding(con,{'logo':'','banner':''})['banner_custom']
