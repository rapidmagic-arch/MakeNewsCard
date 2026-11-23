"""Issue lifecycle and AI adapter tests; no real network/API key required."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from meditip.db import connect, setup, ensure_edition, edition_rows, save_item
from meditip.edition import prepare, update_decision, set_top_order, bulk_industry, import_ai
from meditip.render import render
from meditip.workflow import week_label, confirm, confirmed_html, confirm_details
from meditip.ai_review import review_payload, analyze, ask

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'templates'/'892_slots_original.html'

@pytest.fixture
def issue_db(tmp_path):
    with connect(tmp_path/'issues.db') as con:
        setup(con)
        ensure_edition(con,'week','2026-11-16','2026-11-22')
        ensure_edition(con,'special','2026-11-16','2026-11-22')
        save_item(con,{'source_key':'press','source_group':'mfds','section':'mfds.press',
            'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=123','title':'식약처 고시 자료',
            'published_at':'2026-11-17'})
        save_item(con,{'source_key':'dailypharm','source_group':'industry','section':'industry.unclassified',
            'url':'https://www.dailypharm.com/user/news/123','title':'GLP-1 시장 확대',
            'published_at':'2026-11-17'})
        con.commit()
        prepare(con,'week');prepare(con,'special')
        yield con


def test_week_label_year_boundary_and_custom():
    assert week_label('2026-11-16','2026-11-22')=='2026-W47'
    assert week_label('2026-12-28','2027-01-03')=='2026-W53'
    assert '사용자 지정' in week_label('2026-11-16','2026-11-19')


def test_confirm_snapshot_immutable_and_no_editorial_mutation(issue_db):
    rows=edition_rows(issue_db,'week')
    industry=next(x for x in rows if x['source_group']=='industry')
    update_decision(issue_db,'week',industry['id'],{'include_detail':True,'summary_override':'담당자 확인 요약'})
    result=confirm(issue_db,'week',TEMPLATE,'담당자','893')
    assert result['status']=='confirmed' and len(result['html_sha256'])==64
    assert confirm_details(issue_db,'week')['issue_number']=='893'
    first=confirmed_html(issue_db,'week')
    assert '담당자 확인 요약' in first
    assert '언론기사 후보' not in first and '확인된 수록 자료 없음' not in first
    save_item(issue_db,{'source_key':'press','source_group':'mfds','section':'mfds.press',
       'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=123','title':'식약처 변경된 원본',
       'published_at':'2026-11-17'})
    issue_db.commit()
    assert confirmed_html(issue_db,'week')==first
    assert hashlib.sha256(first.encode()).hexdigest()==result['html_sha256']
    with pytest.raises(ValueError):prepare(issue_db,'week')
    with pytest.raises(ValueError):update_decision(issue_db,'week',industry['id'],{'include_detail':False})
    with pytest.raises(ValueError):set_top_order(issue_db,'week',[])
    with pytest.raises(ValueError):bulk_industry(issue_db,'week','include')
    with pytest.raises(ValueError):import_ai(issue_db,'week',{'items':[]})
    with pytest.raises(ValueError):confirm(issue_db,'week',TEMPLATE,'담당자','893')
    # A separate issue can use exactly the same source week but not an already-issued number.
    with pytest.raises(ValueError):confirm(issue_db,'special',TEMPLATE,'담당자','893')
    assert confirm(issue_db,'special',TEMPLATE,'담당자','특별01')['status']=='confirmed'


def test_draft_renders_warnings_but_confirmed_removes_operator_text(issue_db):
    draft=render(issue_db,'week',TEMPLATE)
    assert '언론기사 후보 1건' in draft
    final=render(issue_db,'week',TEMPLATE,final=True)
    assert '언론기사 후보 1건' not in final
    assert '미확인' not in final or '미확인' in [x['title'] for x in edition_rows(issue_db,'week')]


def test_api_input_identity_and_model_results(issue_db,monkeypatch):
    row_id=next(x['id'] for x in edition_rows(issue_db,'week') if x['source_group']=='industry')
    payload=review_payload(issue_db,'week',[row_id])
    assert len(payload['items'])==1
    assert len(payload['input_sha256'])==64
    row=payload['items'][0]
    fake={ 'output':[{'content':[{'type':'output_text','text':json.dumps({'items':[{
       'id':row['id'],'section':'industry.market','score':90,'recommended':True,
       'relevance':'relevant','reason':'시장 동향 제안 · 원문 미확인','summary':'초안 요약'}]})}]}]}
    called=[]
    def post(url,**kw):
        called.append((url,kw['json']))
        return Mock(raise_for_status=lambda:None,json=lambda:fake)
    monkeypatch.setenv('OPENAI_API_KEY','offline-test-only')
    monkeypatch.setattr('meditip.ai_review.requests.post',post)
    result=analyze(payload,model='offline-test-model')
    assert len(result['items'])==1 and result['input_sha256']==payload['input_sha256']
    assert called[0][1]['store'] is False
    import_ai(issue_db,'week',result)
    candidate=next(x for x in edition_rows(issue_db,'week') if x['id']==row['id'])
    assert candidate['ai_recommended'] and not candidate['include_detail'] and candidate['ai_relevance']=='relevant'


def test_no_api_key_never_silently_falls_back(issue_db,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(ValueError,match='OPENAI_API_KEY'):
        analyze(review_payload(issue_db,'week'))
    with pytest.raises(ValueError,match='OPENAI_API_KEY'):
        ask(issue_db,'week','분류 이유?', [review_payload(issue_db,'week')['items'][0]['id']])


def test_confirmation_needs_operator_and_items(tmp_path):
    with connect(tmp_path/'empty.db') as c:
        setup(c);ensure_edition(c,'empty','2026-11-16','2026-11-22')
        with pytest.raises(ValueError,match='담당자'):confirm(c,'empty',TEMPLATE,'')
        with pytest.raises(ValueError,match='기사가 없는'):confirm(c,'empty',TEMPLATE,'담당자')
        assert c.execute('SELECT COUNT(*) FROM edition_confirmations').fetchone()[0]==0
