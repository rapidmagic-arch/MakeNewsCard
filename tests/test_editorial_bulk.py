"""Regression tests for source preservation, mechanical candidate classification and bulk decisions."""
import json
from pathlib import Path

import pytest

from meditip.db import connect, setup, ensure_edition, save_item, edition_rows
from meditip.edition import prepare, update_decision, bulk_industry, import_ai, industry_proposal
from meditip.render import render

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def edb(tmp_path):
    db = tmp_path/'news.db'
    with connect(db) as c:
        setup(c)
        ensure_edition(c, 'week', '2026-11-16','2026-11-22')
        subjects=[('정책','약가 규제 고시 개정'),('시장','GLP-1 치료제 시장 확대'),('국제','미국 FDA 심사 강화'),('연구','ADC 신약 임상 연구'),('무관','오늘의 날씨 안내')]
        for i,(_,title) in enumerate(subjects):
            save_item(c,{'source_group':'industry','source_key':'dailypharm','section':'industry.unclassified',
                         'url':f'https://www.dailypharm.com/user/news/{50000+i}','title':title,
                         'published_at':'2026-11-17'})
        c.commit()
        prepare(c,'week')
        yield c

def test_rule_classification_and_initially_unselected(edb):
    rows=edition_rows(edb,'week')
    assert len(rows)==5 and not any(x['include_detail'] for x in rows)
    expected={'약가 규제 고시 개정':'industry.policy','GLP-1 치료제 시장 확대':'industry.market',
              '미국 FDA 심사 강화':'industry.global','ADC 신약 임상 연구':'industry.rnd',
              '오늘의 날씨 안내':'industry.unclassified'}
    for x in rows:
        assert x['rule_section']==expected[x['title']]
        assert bool(x['rule_recommended']) == (x['title']!='오늘의 날씨 안내')

def test_recommend_bulk_uses_only_candidates_and_preserves_human_edit(edb):
    rows=edition_rows(edb,'week')
    weather=next(x for x in rows if x['title']=='오늘의 날씨 안내')
    policy=next(x for x in rows if '약가' in x['title'])
    update_decision(edb,'week',policy['id'],{'include_detail':False,'section_override':'industry.rnd'})
    result=bulk_industry(edb,'week','apply_recommended')
    assert result['updated']==3 and result['protected']==1 and result['not_recommended']==1
    rows={x['id']:x for x in edition_rows(edb,'week')}
    assert rows[policy['id']]['include_detail']==0
    assert rows[policy['id']]['section_override']=='industry.rnd'
    assert rows[weather['id']]['include_detail']==0
    assert sum(bool(x['include_detail']) for x in rows.values())==3
    assert bulk_industry(edb,'week','apply_recommended')['updated']==0


def test_imported_ai_priority_not_applied_until_user_action(edb):
    row=next(x for x in edition_rows(edb,'week') if x['title']=='오늘의 날씨 안내')
    import_ai(edb,'week',{'items':[{'id':row['id'],'score':88,'reason':'GPT가 추천한 기사 예시',
                                    'section':'industry.global','recommended':True,'summary':'일반 요약 예시'}]})
    candidate=next(x for x in edition_rows(edb,'week') if x['id']==row['id'])
    assert candidate['include_detail']==0
    assert candidate['ai_recommended']==1
    changed=bulk_industry(edb,'week','apply_recommended',[row['id']])
    assert changed['updated']==1
    output=render(edb,'week',ROOT/'templates'/'892_slots_original.html')
    assert row['title'] in output
    assert 'GPT가 추천한 기사' not in output  # suggestions are stored as editorial metadata, not copied blindly


def test_migration_preserves_old_selected_editorial_choices(tmp_path):
    db=tmp_path/'legacy.db'
    with connect(db) as c:
        setup(c);ensure_edition(c,'week','2026-11-16','2026-11-22')
        save_item(c,{'source_group':'industry','source_key':'yakup','section':'industry.unclassified',
                     'url':'https://www.yakup.com/news/123','title':'신약 임상 연구','published_at':'2026-11-17'})
        c.commit();prepare(c,'week')
        key=edition_rows(c,'week')[0]['id']
        c.execute('UPDATE decisions SET include_detail=1,detail_reviewed=0 WHERE edition_id=? AND item_id=?',('week',key))
        c.commit()
        setup(c)
        assert edition_rows(c,'week')[0]['detail_reviewed']==1
        assert bulk_industry(c,'week','exclude')['protected']==1
        assert edition_rows(c,'week')[0]['include_detail']==1


def test_invalid_bulk_scope_rejected(edb):
    with pytest.raises(ValueError):bulk_industry(edb,'week','include',['unknown'])
    with pytest.raises(ValueError):bulk_industry(edb,'week','bad')
