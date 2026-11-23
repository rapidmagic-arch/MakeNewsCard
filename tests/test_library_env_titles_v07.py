"""Regression tests: local credentials, newsletter library, and noisy source titles."""
import os
from pathlib import Path
import pytest
from meditip.app_config import load_project_env
from meditip.collect import parse_public_list
from meditip.db import connect, setup, ensure_edition, save_item
from meditip.edition import group_proposal, proposal_for, prepare
from meditip.library import library_page, archived_html
from meditip.workflow import confirm

ROOT=Path(__file__).resolve().parents[1]

def test_project_env_loads_without_overriding_session_vars(tmp_path,monkeypatch):
    (tmp_path/'.env').write_text('OPENAI_API_KEY=local-test-value\nOPENAI_MODEL=gpt-test-model\n')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    assert load_project_env(tmp_path)
    assert os.environ['OPENAI_API_KEY']=='local-test-value'
    assert os.environ['OPENAI_MODEL']=='gpt-test-model'
    monkeypatch.setenv('OPENAI_API_KEY','inherited-session-key')
    assert load_project_env(tmp_path)
    assert os.environ['OPENAI_API_KEY']=='inherited-session-key'

def test_dotenv_example_keeps_key_out_of_git():
    ignores=(ROOT/'.gitignore').read_text().splitlines()
    assert '.env' in ignores and '.env.*' in ignores and '!.env.example' in ignores
    assert (ROOT/'.env.example').exists()
    assert 'OPENAI_API_KEY=' in (ROOT/'.env.example').read_text()
    assert 'OPENAI_API_KEY=sk-' not in (ROOT/'.env.example').read_text()

def test_library_pagination_search_confirmation_and_immutable_html(tmp_path):
    with connect(tmp_path/'library.db') as con:
        setup(con)
        for n in range(25):
            ensure_edition(con,f'issue-{n:02d}','2026-11-02','2026-11-08',f'제목 {n:02d}')
        ensure_edition(con,'draft','2026-11-09','2026-11-15','다음 편집 중')
        save_item(con,{'source_key':'press','source_group':'mfds','section':'mfds.press',
                       'url':'https://www.mfds.go.kr/brd/m_99/view.do?seq=99818','title':'제약 동향',
                       'published_at':'2026-11-04'})
        con.commit()
        prepare(con,'issue-00')
        confirm(con,'issue-00',ROOT/'templates'/'892_slots_original.html','편집자','893')
        html=archived_html(con,'issue-00')
        assert html and '제약 동향' in html
        assert archived_html(con,'draft') is None
        page=library_page(con,status='all',page=1,page_size=12)
        assert page['total']==26 and page['pages']==3 and len(page['items'])==12
        assert len(library_page(con,status='all',page=3,page_size=12)['items'])==2
        assert library_page(con,status='confirmed')['total']==1
        assert library_page(con,status='draft')['total']==25
        assert library_page(con,status='all',search='893')['total']==1
        assert library_page(con,status='all',search='%')['total']==0
        assert archived_html(con,'issue-00')==html
    with connect(tmp_path/'library.db') as con:
        assert archived_html(con,'issue-00')==html

def test_library_invalid_input_is_rejected(tmp_path):
    with connect(tmp_path/'db.db') as con:
        setup(con)
        for args in (dict(status='missing'),dict(page=0),dict(page_size=0),dict(search='x'*101)):
            with pytest.raises(ValueError):library_page(con,**args)
        with pytest.raises(ValueError):archived_html(con,'x'*300)

def test_title_from_nested_heading_preserves_raw_link_text():
    html='''<article><time datetime="2026-11-23">11/23</time>
    <a href="/user/news/12345"><h3>의약품 규제 개정 관련 뉴스</h3><p>이 내용은 기사에 붙은 매우 긴 부연 설명입니다. </p></a></article>'''
    result=parse_public_list(html,'https://www.dailypharm.com/','dailypharm','industry','industry.unclassified')
    assert len(result)==1 and result[0]['title']=='의약품 규제 개정 관련 뉴스'
    assert result[0]['published_at']=='2026-11-23'
    assert result[0]['verification']=='metadata_only'
    assert '긴 부연 설명' in result[0]['original_metadata']['raw_link_text']

def test_unverified_long_link_is_not_auto_recommended():
    raw='화제의 기사가 발행되었습니다 본문 설명과 기자 이름이 뒤에 붙었습니다. '*15
    html=f'<article><a href="/user/news/5001">{raw}</a></article>'
    items=parse_public_list(html,'https://www.dailypharm.com/','dailypharm','industry','industry.unclassified')
    assert len(items)==1
    x=items[0]
    assert x['verification']=='needs_title_review'
    assert x['title'].startswith('[제목 확인 필요]')
    assert len(x['original_metadata']['raw_link_text'])>len(x['title'])
    assert group_proposal(x)[:3]==('industry.unclassified','review_needed',False)

def test_existing_oversized_titles_need_editorial_review():
    row={'verification':'metadata_only','title':'기사와 광고 본문이 뒤섞인 링크 텍스트 '*20,
         'section':'industry.unclassified','section_override':None,'ai_recommended':True}
    assert not group_proposal(row)[2]
    assert proposal_for(row)[0] is False

def test_duplicate_bad_link_does_not_replace_clean_headline():
    text='무관한 긴 설명 '*60
    html=('<article><a href="/user/news/30001"><h3>허가 규제 관련 정확한 기사 제목</h3></a>'
          '<a href="/user/news/30001">'+text+'</a></article>')
    found=parse_public_list(html,'https://www.dailypharm.com/','dailypharm','industry','industry.unclassified')
    assert len(found)==1 and found[0]['title']=='허가 규제 관련 정확한 기사 제목'
