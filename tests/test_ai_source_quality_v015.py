"""Source-specific headline/date and AI partial failure regression."""
import json
from pathlib import Path
import pytest
from meditip.ai_review import analyze,review_payload,allowed_sections
from meditip.collect import parse_public_list,parse_media_detail
from meditip.db import connect,setup,save_item,ensure_edition,edition_rows
from meditip.edition import prepare,update_decision,set_top_order,import_ai,repair_media_metadata
from meditip.metadata_quality import title_needs_review
from meditip.render import render
from meditip.workflow import confirm,confirmed_html

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates/892_slots_original.html'
YAK='https://www.yakup.com/news/index.html?mode=view&nid=335674'
DAILY='https://www.dailypharm.com/user/news/344973'
TITLE='30 년 연구를 이어 온 신약 개발 소식'

def test_yakup_main_list_not_rank_or_body_date():
    html=f'''<a href="{YAK}"><div class="list_div"><div class="title_con"><span>{TITLE}</span></div>
      <div class="text_con">합성 기사 2020-01-01</div><div class="name_con"><span class="date">2026.11.25</span></div></div></a>
      <a href="{YAK}"><table><tr><td class="num_td">2</td><td class="info_td">{TITLE}</td></tr></table></a>'''
    rows=parse_public_list(html,'https://www.yakup.com/news/index.html','yakup','industry','industry.unclassified')
    assert len(rows)==1 and rows[0]['title']==TITLE and rows[0]['published_at']=='2026-11-25'
    assert not title_needs_review(rows[0])
    assert title_needs_review({'title':'2 '+TITLE,'source_key':'yakup','original_metadata':'{}'})

def test_dailypharm_list_preserves_real_digit_and_detail_date():
    html=f'''<a href="{DAILY}"><div class="lin_title">2상 임상시험 성과</div><div class="lin_cont">2020-01-01</div>
        <div class="lin_data"><div>2026-11-25 06:00:54</div><div>기자</div></div></a>
        <a href="{DAILY}"><span>2</span>2상 임상시험 성과</a>'''
    rows=parse_public_list(html,'https://www.dailypharm.com/user/news','dailypharm','industry','industry.unclassified')
    assert len(rows)==1 and rows[0]['title']=='2상 임상시험 성과' and rows[0]['published_at']=='2026-11-25'
    detail=f'<meta property="og:url" content="{DAILY}"><meta property="og:title" content="2상 임상시험 성과"><meta property="article:published_time" content="2026-11-25T06:00:54+09:00"><meta property="article:modified_time" content="2026-11-26">'
    assert parse_media_detail(detail,DAILY,'dailypharm')['published_at']=='2026-11-25'
    with pytest.raises(ValueError):parse_media_detail(detail.replace('344973','344999'),DAILY,'dailypharm')
    with pytest.raises(ValueError):parse_media_detail(detail.replace('article:published_time','article:modified_time'),DAILY,'dailypharm')

def test_yakup_explicit_published_only():
    html=f'<div class="news_view_div"><div class="title_con"><div class="stitle_con">{TITLE}</div></div><div class="date_con"><span>입력 2026.11.25 06:00</span><span>수정 2026.11.26</span></div></div>'
    assert parse_media_detail(html,YAK,'yakup')=={'title':TITLE,'published_at':'2026-11-25'}
    with pytest.raises(ValueError):parse_media_detail(html.replace('입력','수정'),YAK,'yakup')

def test_ai_schema_and_partial_retry(monkeypatch,tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    with connect(tmp_path/'db.sqlite') as con:
        setup(con);ensure_edition(con,'w','2026-11-16','2026-11-22')
        ids=[save_item(con,dict(source_key='dailypharm',source_group='industry',section='industry.unclassified',
             title='기사 테스트 '+str(i),url='https://www.dailypharm.com/user/news/'+str(100+i),published_at='2026-11-17')) for i in range(2)]
        con.commit();prepare(con,'w')
        calls=[]
        def fake(messages,schema,model):
            assert schema['properties']['items']['items']['properties']['section']['enum']==list(allowed_sections('industry'))
            batch=json.loads(messages[1]['content']);calls.append([x['id'] for x in batch])
            return json.dumps({'items':[dict(id=x['id'],section='mfds.press' if x['id']==ids[1] else 'industry.market',score=80,recommended=True,relevance='relevant',reason='제안',summary='요약') for x in batch]})
        monkeypatch.setattr('meditip.ai_review._call_api',fake)
        payload=review_payload(con,'w',ids)
        result=analyze(payload,allow_partial=True)
        assert [x['id'] for x in result['items']]==[ids[0]] and [x['id'] for x in result['failures']]==[ids[1]]
        sub=review_payload(con,'w',[ids[0]])
        assert import_ai(con,'w',{**result,'input_sha256':sub['input_sha256']})==1
        rows={x['id']:x for x in edition_rows(con,'w')}
        assert rows[ids[0]]['ai_score']==80 and rows[ids[1]]['ai_score'] is None and not rows[ids[0]]['include_detail']
        with pytest.raises(ValueError):analyze(payload)
        with pytest.raises(ValueError):import_ai(con,'w',{'items':[{'id':ids[1],'section':'industry.bad'}]})

def test_recheck_legacy_retains_selection_and_frozen_snapshot(tmp_path):
    with connect(tmp_path/'db.sqlite') as con:
        setup(con)
        for eid in ('draft','archive'):ensure_edition(con,eid,'2026-11-16','2026-11-22')
        iid=save_item(con,dict(source_key='yakup',source_group='industry',section='industry.unclassified',
          title='2 '+TITLE,url=YAK,source_id='335674',published_at='2026-11-17'))
        con.commit()
        for eid in ('draft','archive'):
            prepare(con,eid);update_decision(con,eid,iid,{'include_detail':True,'company_selected':True,'summary_override':'수동 요약'});set_top_order(con,eid,[iid])
        confirm(con,'archive',TEMPLATE,'담당자')
        frozen=confirmed_html(con,'archive')
        row=edition_rows(con,'draft')[0]
        result=repair_media_metadata(con,'draft',iid,row['content_sha'],{'title':TITLE,'published_at':'2026-11-25'})
        assert result['out_of_period']
        row=edition_rows(con,'draft')[0]
        assert row['title']==TITLE and not title_needs_review(row)
        assert row['include_detail'] and row['company_selected'] and row['top_selected'] and row['summary_override']=='수동 요약'
        for mode in ('classic','outlook_cards'):
            h=render(con,'draft',TEMPLATE,preview=True,template_id=mode)
            assert TITLE in h and '2 '+TITLE not in h and '약업신문' in h
        with pytest.raises(ValueError,match='기간 밖'):confirm(con,'draft',TEMPLATE,'담당자')
        assert confirmed_html(con,'archive')==frozen
