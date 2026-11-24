"""Regression fixtures modeled on observed public list/detail markup; body text is synthetic."""
import json
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from meditip.collect import parse_public_list,parse_medicaltimes_detail
from meditip.metadata_quality import title_needs_review
from meditip.db import connect,setup,ensure_edition,save_item,edition_rows
from meditip.edition import prepare,update_decision,set_top_order,repair_medicaltimes_metadata,group_proposal
from meditip.workflow import confirm,confirmed_html
from meditip.render import render

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates/892_slots_original.html'
BASE='https://www.medicaltimes.com/Main/News/List.html'
URL='https://www.medicaltimes.com/Main/News/NewsView.html?ID=1172075'
TITLE='노을 메디카서 해외 공급 논의…유통망 확대 추진'
DETAIL=f'<div class="viewTitle_wrap"><h3 id="NewsTitle">{TITLE}</h3><div class="date_info"><span>발행날짜: 2026-11-23 13:32:43</span><span>수정날짜: 2026-11-24</span></div></div>'

def test_dedicated_medicaltimes_list_and_duplicate_sidebar():
    html=f'''<article class="newsList_cont clearfix"><a href="{URL}">
    <div class="newsList_cont_txt"><h4 class="headLine">{TITLE}</h4><div class="list_txt">[메디칼타임즈=기자] 합성 본문 2020-01-01</div></div>
    <span class="newsList_cont_date">2026-11-23 13:32:43<span>진단</span></span></a></article>
    <aside><a href="{URL}">다른 제목</a></aside>'''
    rows=parse_public_list(html,BASE,'medicaltimes','industry','industry.unclassified')
    assert len(rows)==1
    assert rows[0]['title']==TITLE and rows[0]['published_at']=='2026-11-23'
    assert rows[0]['verification']=='metadata_only'
    assert '합성 본문' not in json.dumps(rows[0],ensure_ascii=False)

def test_missing_dedicated_fields_do_not_use_body_or_sidebar():
    html=f'''<article class="newsList_cont clearfix"><a href="{URL}">
    <div class="list_txt">[메디칼타임즈=기자] 합성 본문 2026-11-23 13:32:43</div></a></article>
    <aside><a href="{URL}"><h4>관련 기사 제목</h4></a></aside>'''
    row=parse_public_list(html,BASE,'medicaltimes','industry','industry.unclassified')[0]
    assert row['verification']=='needs_title_review' and row['published_at'] is None
    assert group_proposal(row)[:3]==('industry.unclassified','review_needed',False)
    assert title_needs_review({'source_key':'medicaltimes','title':'정상처럼 보이는 제목 [메디칼타임즈=기자] 본문'})
    assert title_needs_review({'source_key':'medicaltimes','title':'정상처럼 보이는 제목 2026-11-23 13:32:43 진단'})

def test_detail_requires_explicit_publication_label():
    assert parse_medicaltimes_detail(DETAIL,URL)==dict(title=TITLE,published_at='2026-11-23')
    with pytest.raises(ValueError):parse_medicaltimes_detail(DETAIL.replace('발행날짜:','수정날짜:'),URL)
    with pytest.raises(ValueError):parse_medicaltimes_detail('<h3>다른 제목</h3>',URL)
    with pytest.raises(ValueError):parse_medicaltimes_detail(DETAIL,'https://example.org/')

def test_repair_preserves_human_decisions_and_frozen_issue(tmp_path):
    with connect(tmp_path/'repair.db') as con:
        setup(con)
        for eid in ('draft','archive'):ensure_edition(con,eid,'2026-11-16','2026-11-22')
        old=TITLE+' [메디칼타임즈=기자] 합성 본문'
        iid=save_item(con,dict(source_key='medicaltimes',source_group='industry',section='industry.unclassified',
             url=URL,title=old,source_id='1172075',published_at=None,verification='needs_title_review'))
        con.commit()
        for eid in ('draft','archive'):
            prepare(con,eid,extra_ids=[iid])
            update_decision(con,eid,iid,{'include_detail':True,'title_override':'담당자 편집 제목','summary_override':'담당자 요약',
                                      'section_override':'industry.market','company_selected':True})
            set_top_order(con,eid,[iid])
        con.execute("UPDATE decisions SET ai_score=77,ai_reason='이전 분석',ai_recommended=1 WHERE edition_id='draft'")
        con.commit()
        confirm(con,'archive',TEMPLATE,'편집자','893')
        frozen=confirmed_html(con,'archive')
        old_sha=edition_rows(con,'draft')[0]['content_sha']
        result=repair_medicaltimes_metadata(con,'draft',iid,old_sha,parse_medicaltimes_detail(DETAIL,URL))
        assert result['changed'] and result['out_of_period']
        row=edition_rows(con,'draft')[0]
        assert row['title']==TITLE and row['published_at']=='2026-11-23'
        assert row['title_override']=='담당자 편집 제목' and row['summary_override']=='담당자 요약'
        assert row['section_override']=='industry.market' and row['include_detail'] and row['company_selected'] and row['top_selected']
        assert row['rule_section']!='industry.unclassified' and row['ai_score'] is None and not row['ai_recommended']
        assert con.execute("SELECT COUNT(*) FROM item_versions WHERE item_id=?",(iid,)).fetchone()[0]==2
        assert confirmed_html(con,'archive')==frozen
        snapshot=json.loads(con.execute("SELECT raw_json FROM edition_confirmations WHERE edition_id='archive'").fetchone()[0])
        assert snapshot['items'][0]['title']==old
        with pytest.raises(ValueError):repair_medicaltimes_metadata(con,'draft',iid,old_sha,parse_medicaltimes_detail(DETAIL,URL))
        with pytest.raises(ValueError):repair_medicaltimes_metadata(con,'archive',iid,row['content_sha'],parse_medicaltimes_detail(DETAIL,URL))
        soup=BeautifulSoup(render(con,'draft',TEMPLATE,preview=True),'html.parser')
        contact=soup.select_one('[data-contact-slot]')
        footer=soup.select_one('[data-image-slot="footer"]')
        assert contact.parent.parent==footer.parent.parent and contact.parent!=footer.parent
