import json
import sqlite3
import tempfile
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from meditip.db import connect,setup,save_item,log_run,ensure_edition,edition_rows
from meditip.edition import prepare,set_top_order,update_decision,import_ai
from meditip.collect import parse_feed,parse_public_list
from meditip.render import render

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def testdb(tmp_path):
    p=tmp_path/'news.db'
    with connect(p) as c:
        setup(c)
        data=json.loads((ROOT/'fixtures'/'mfds_2026-11-16_22_partial.json').read_text())
        from meditip.collect import import_snapshot
        import_snapshot(c,data,'test_fixture')
        ensure_edition(c,'test','2026-11-16','2026-11-22','test edition')
        prepare(c,'test')
        yield c

def test_seven_records_and_top_four(testdb):
    rows=edition_rows(testdb,'test')
    assert len(rows)==7
    assert sum(bool(x['top_selected']) for x in rows)==4
    assert all(x['include_detail'] for x in rows)

def test_top_is_independent_of_mandatory(testdb):
    rows=edition_rows(testdb,'test')
    top=[r['id'] for r in rows if r['top_selected']]
    set_top_order(testdb,'test',top[:2])
    assert sum(x['top_selected'] for x in edition_rows(testdb,'test'))==2
    assert sum(x['include_detail'] for x in edition_rows(testdb,'test'))==7
    with pytest.raises(ValueError):update_decision(testdb,'test',top[0],{'include_detail':False})

def test_top_variable_more_than_four(testdb):
    ids=[x['id'] for x in edition_rows(testdb,'test')]
    set_top_order(testdb,'test',ids[:6])
    html=render(testdb,'test',ROOT/'templates'/'892_slots_original.html')
    soup=BeautifulSoup(html,'html.parser')
    assert len(soup.select('[data-record-id]'))>=7
    assert sum(x['top_selected'] for x in edition_rows(testdb,'test'))==6
    assert '{{top4_' not in html
    assert 'MEDITIP MVP 테스트 · 892호' not in html

def test_preserve_edit_after_prepare(testdb):
    ids=[x['id'] for x in edition_rows(testdb,'test')]
    set_top_order(testdb,'test',ids[:2]);prepare(testdb,'test')
    assert sum(x['top_selected'] for x in edition_rows(testdb,'test'))==2
    set_top_order(testdb,'test',[]);prepare(testdb,'test')
    assert sum(x['top_selected'] for x in edition_rows(testdb,'test'))==0

def test_ai_cannot_overwrite_human_override(testdb):
    r=edition_rows(testdb,'test')[0]
    set_top_order(testdb,'test',[r['id']])
    update_decision(testdb,'test',r['id'],{'summary_override':'사용자 편집 요약'})
    import_ai(testdb,'test',{'items':[{'id':r['id'],'summary':'AI 제안','score':75,'reason':'관심 주제','recommended':True}]})
    x=[x for x in edition_rows(testdb,'test') if x['id']==r['id']][0]
    assert x['summary_override']=='사용자 편집 요약'
    assert x['ai_summary']=='AI 제안'
    assert '사용자 편집 요약' in render(testdb,'test',ROOT/'templates'/'892_slots_original.html')

def test_escaping_untrusted_text(testdb):
    r=edition_rows(testdb,'test')[0]
    set_top_order(testdb,'test',[r['id']]);update_decision(testdb,'test',r['id'],{'title_override':'<script>bad()</script>', 'summary_override':'<img src=x onerror=alert(1)>'})
    html=render(testdb,'test',ROOT/'templates'/'892_slots_original.html')
    assert '&lt;script&gt;bad()&lt;/script&gt;' in html
    assert '<script>bad()</script>' not in html
    assert 'onerror=alert(1)&gt;' in html

def test_versions_not_overwritten(testdb):
    r=edition_rows(testdb,'test')[0]
    snap={ 'id':r['id'],'source_key':r['source_key'],'source_group':r['source_group'],
      'section':r['section'],'url':r['url'],'title':'수정된 제목', 'published_at':r['published_at']}
    save_item(testdb,snap);testdb.commit()
    version=testdb.execute('SELECT COUNT(*) FROM item_versions WHERE item_id=?',(r['id'],)).fetchone()[0]
    assert version==2

def test_zero_is_not_collection_failed(testdb):
    log_run(testdb,'mfds_test','2026-11-16','2026-11-22','failed',0,0,{'reason':'network blocked'})
    r=testdb.execute('SELECT * FROM runs WHERE source_key=?',('mfds_test',)).fetchone()
    assert r['status']=='failed' and r['records_seen']==0

def test_rss_parser():
    feed=b'''<rss version="2.0"><channel><item><title>Test MFDS guidance</title><link>https://www.mfds.go.kr/brd/m_99/view.do?seq=11</link><pubDate>Mon, 16 Nov 2026 08:00:00 +0900</pubDate></item></channel></rss>'''
    out=parse_feed(feed,'https://www.mfds.go.kr/www/rss/brd.do?brdId=ntc0021','press','mfds.press')
    assert len(out)==1 and out[0]['published_at']=='2026-11-16'

def test_public_list_parser():
    markup=b'<table><tr><td>2026.11.17</td><td><a href="/brd/m_209/view.do?seq=5001">Official notice title</a></td></tr></table>'
    out=parse_public_list(markup,'https://www.mfds.go.kr/brd/m_209/list.do','preannouncements','mfds','mfds.regulations')
    assert out[0]['published_at']=='2026-11-17'
    assert out[0]['source_id']=='5001'

def test_clinical_csv_import_and_table(tmp_path,testdb):
    from meditip.collect import import_approval_csv
    f=tmp_path/'approvals.csv'
    f.write_text('의뢰자,제품명,임상시험제목,임상시험 단계,승인일,승인유형\n샘플의뢰자,샘플제제,시험 샘플 제목,3상,2026-11-18,변경승인\n',encoding='utf-8-sig')
    assert import_approval_csv(testdb,f,'clinical')['imported']==1
    prepare(testdb,'test')
    html=render(testdb,'test',ROOT/'templates'/'892_slots_original.html')
    assert '샘플의뢰자' in html and '변경승인' not in html # type stored, but not invented in required five columns
    assert '데이터 수집 연동 전' not in html


def test_mfds_same_post_two_urls_renders_once_without_data_loss(testdb):
    # Two URLs for the same board sequence can differ in paging/search params.
    base='https://www.mfds.go.kr/brd/m_99/view.do?seq=91919'
    title='동일한 식약처 원본을 두 URL에서 발견한 경우'
    for suffix in ('&page=1', '&page=2'):
        save_item(testdb, {'source_key':'press','source_group':'mfds',
                  'section':'mfds.press','url':base+suffix,'title':title,
                  'published_at':'2026-11-17'})
    testdb.commit()
    prepare(testdb,'test')
    rows=[r for r in edition_rows(testdb,'test') if r['title']==title]
    assert len(rows)==2  # original evidence and decisions are retained
    set_top_order(testdb,'test',[x['id'] for x in rows])
    html=render(testdb,'test',ROOT/'templates'/'892_slots_original.html')
    soup=BeautifulSoup(html,'html.parser')
    assert len(soup.find_all('a',string=title))==2  # one TOP + one detailed listing
    assert len(testdb.execute('SELECT id FROM items WHERE title=?',(title,)).fetchall())==2


def test_industry_candidates_only_render_after_human_inclusion(testdb):
    source={'source_key':'dailypharm','source_group':'industry','section':'industry.unclassified',
            'url':'https://www.dailypharm.com/user/news/999000','title':'산업 분야 미분류 수집 기사',
            'published_at':'2026-11-17','mandatory':False}
    save_item(testdb,source)
    testdb.commit()
    prepare(testdb,'test')
    rows=[r for r in edition_rows(testdb,'test') if r['title']==source['title']]
    assert len(rows)==1 and not rows[0]['include_detail']
    html=render(testdb,'test',ROOT/'templates'/'892_slots_original.html')
    assert '언론기사 후보 1건이 있지만' in html
    update_decision(testdb,'test',rows[0]['id'],{'include_detail':True})
    html=render(testdb,'test',ROOT/'templates'/'892_slots_original.html')
    assert source['title'] in html
    assert '미분류 · 담당자 검토 필요' in html


def test_identical_headlines_from_different_publishers_not_collapsed(testdb):
    from meditip.render import unique_for_display
    common={'source_group':'industry','title':'동일 제목 비교', 'published_at':'2026-11-17'}
    rows=[{**common,'id':'a','source_key':'dailypharm','url':'https://www.dailypharm.com/a'},
          {**common,'id':'b','source_key':'yakup','url':'https://www.yakup.com/b'}]
    assert len(list(unique_for_display(rows)))==2
