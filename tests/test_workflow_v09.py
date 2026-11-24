"""Regression coverage for v0.9 editorial policy and repeat storage."""
import json
from pathlib import Path
import pytest
from meditip.db import connect, setup, ensure_edition, save_item, edition_rows
from meditip.edition import prepare, set_top_order, update_decision
from meditip.render import render, top_output_rows
from meditip.workflow import confirm, confirmed_html

TEMPLATE=Path(__file__).resolve().parents[1]/'templates'/'892_slots_original.html'

@pytest.mark.parametrize('template_id',['classic','outlook_cards'])
def test_top_output_limit(tmp_path,template_id):
    with connect(tmp_path/'test.db') as con:
        setup(con)
        ensure_edition(con,'w','2026-11-16','2026-11-22',target=5)
        ids=[]
        for i in range(9):
            ids.append(save_item(con,dict(source_key='dailypharm',source_group='industry',
                section='industry.policy',url=f'https://www.dailypharm.com/user/news/{100+i}',
                title=f'UniqueTOP-{i}-END',published_at='2026-11-17')))
        con.commit()
        prepare(con,'w')
        set_top_order(con,'w',ids)
        con.execute('UPDATE editions SET template_id=? WHERE id=?',(template_id,'w'))
        con.commit()
        rows=edition_rows(con,'w')
        assert len([x for x in rows if x['top_selected']])==9
        assert [x['id'] for x in top_output_rows(rows,5)]==ids[:5]
        assert len(top_output_rows(rows,100))==9
        assert top_output_rows(rows,0)==[]
        html=render(con,'w',TEMPLATE,preview=True)
        assert all(f'UniqueTOP-{i}-END' in html for i in range(5))
        assert all(f'UniqueTOP-{i}-END' not in html for i in range(5,9))
        set_top_order(con,'w',ids[::-1])
        html=render(con,'w',TEMPLATE,preview=True)
        assert 'UniqueTOP-8-END' in html and 'UniqueTOP-0-END' not in html
        confirm(con,'w',TEMPLATE,'reviewer')
        frozen=confirmed_html(con,'w')
        assert 'UniqueTOP-8-END' in frozen and 'UniqueTOP-0-END' not in frozen
        snap=json.loads(con.execute('SELECT raw_json FROM edition_confirmations WHERE edition_id=?',('w',)).fetchone()[0])
        assert snap['top_output_ids']==ids[::-1][:5]

def test_repeat_storage_preserves_decisions(tmp_path):
    with connect(tmp_path/'test.db') as con:
        setup(con)
        ensure_edition(con,'w','2026-11-16','2026-11-22')
        item=dict(source_key='dailypharm',source_group='industry',section='industry.policy',
                  url='https://www.dailypharm.com/user/news/123',title='Original',published_at='2026-11-17')
        stats={}
        iid=save_item(con,item,stats=stats)
        con.commit()
        prepare(con,'w')
        update_decision(con,'w',iid,dict(include_detail=True,title_override='Human'))
        assert save_item(con,{**item,'url':item['url']+'?utm_source=rss'},stats=stats)==iid
        assert save_item(con,{**item,'title':'Updated'},stats=stats)==iid
        con.commit()
        prepare(con,'w')
        assert stats==dict(new=1,unchanged=1,changed=1)
        assert con.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1
        assert con.execute('SELECT COUNT(*) FROM item_versions').fetchone()[0]==2
        rows=edition_rows(con,'w')
        assert len(rows)==1 and rows[0]['include_detail'] and rows[0]['title_override']=='Human'
