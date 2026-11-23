"""Regression checks for issue-scoped provenance, editorial approval and HTML safety."""
from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from meditip.db import connect,setup,save_item,ensure_edition,edition_rows,log_run
from meditip.edition import prepare,update_decision,import_ai,bulk_industry,set_top_order
from meditip.render import render
TEMPLATE=Path(__file__).resolve().parents[1]/'templates'/'892_slots_original.html'

def db(tmp_path):
 c=connect(tmp_path/'regress.db');setup(c)
 ensure_edition(c,'w1','2026-11-16','2026-11-22')
 ensure_edition(c,'w2','2026-11-23','2026-11-29')
 return c
def item(c,source='dailypharm',section='industry.unclassified',date='2026-11-17',tag='1'):
 return save_item(c,{'source_key':source,'source_group':'mfds' if source=='press' else 'industry',
     'section':section,'url':('https://www.mfds.go.kr/brd/m_99/view.do?seq=' if source=='press' else 'https://www.dailypharm.com/user/news/')+tag,
     'title':'회차 검증 기사 '+tag,'published_at':date})

def test_global_undated_not_in_every_edition(tmp_path):
 with db(tmp_path) as c:
  item(c,date=None);c.commit()
  assert prepare(c,'w1')==0 and prepare(c,'w2')==0
  assert c.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1
def test_runs_have_edition_scope(tmp_path):
 with db(tmp_path) as c:
  log_run(c,'press','2026-11-16','2026-11-22','partial',2,10,edition_id='w1')
  log_run(c,'press','2026-11-23','2026-11-29','partial',2,12,edition_id='w2')
  log_run(c,'press','2026-11-16','2026-11-22','partial',2,11)
  assert c.execute("SELECT COUNT(*) FROM runs WHERE edition_id='w1'").fetchone()[0]==1
  assert c.execute("SELECT COUNT(*) FROM runs WHERE edition_id IS NULL").fetchone()[0]==1
def test_ai_summary_only_after_human_override(tmp_path):
 with db(tmp_path) as c:
  iid=item(c);c.commit();prepare(c,'w1')
  set_top_order(c,'w1',[iid])
  import_ai(c,'w1',{'items':[{'id':iid,'recommended':True,'section':'industry.market','summary':'검증 전 AI 요약'}]})
  assert '검증 전 AI 요약' not in render(c,'w1',TEMPLATE)
  out=bulk_industry(c,'w1','apply_recommended',[iid])
  assert out['updated']==1
  row=edition_rows(c,'w1')[0]
  assert row['include_detail'] and row['section_override']=='industry.market'
  assert '검증 전 AI 요약' not in render(c,'w1',TEMPLATE,final=True)
def test_human_can_reverse_inclusion(tmp_path):
 with db(tmp_path) as c:
  iid=item(c);c.commit();prepare(c,'w1')
  update_decision(c,'w1',iid,{'include_detail':True})
  assert bulk_industry(c,'w1','set_inclusion',[iid],False)['updated']==1
  assert not edition_rows(c,'w1')[0]['include_detail']
  assert bulk_industry(c,'w1','set_inclusion',[iid],True)['updated']==1
  assert edition_rows(c,'w1')[0]['include_detail']
def test_mfds_cross_section_duplicate_only_one_link(tmp_path):
 with db(tmp_path) as c:
  u='https://www.mfds.go.kr/brd/m_99/view.do?seq=885511'
  for a,b,source,section in [('a','1','press','mfds.press'),('b','2','guides_staff','mfds.guides')]:
   save_item(c,{'id':a,'source_key':source,'source_group':'mfds','section':section,
          'url':u+'&page='+b,'title':'중복 식약처 제목','published_at':'2026-11-17','mandatory':a=='b'})
  c.commit();prepare(c,'w1')
  h=render(c,'w1',TEMPLATE,final=True)
  assert len(BeautifulSoup(h,'html.parser').find_all('a',string='중복 식약처 제목'))==1
  assert c.execute('SELECT COUNT(*) FROM items').fetchone()[0]==2
  with pytest.raises(ValueError):update_decision(c,'w1','b',{'include_detail':False})
def test_preview_excludes_operator_text(tmp_path):
 with db(tmp_path) as c:
  item(c);c.commit();prepare(c,'w1')
  assert '언론기사 후보 1건이 있지만' in render(c,'w1',TEMPLATE)
  h=render(c,'w1',TEMPLATE,preview=True)
  assert '언론기사 후보 1건이 있지만' not in h and '확인된 수록 자료 없음' not in h
  assert '[미확정 미리보기]' in h
def test_fresh_undated_record_attached_only_to_current_edition(tmp_path):
 with db(tmp_path) as c:
  iid=item(c,date=None);c.commit()
  assert prepare(c,'w1',extra_ids=[iid])==1
  assert prepare(c,'w2')==0
  assert edition_rows(c,'w1')[0]['published_at'] is None
def test_ai_import_hash_and_edition_checked(tmp_path):
 from meditip.ai_review import review_payload
 with db(tmp_path) as c:
  iid=item(c);c.commit();prepare(c,'w1')
  base=review_payload(c,'w1',[iid])
  out={'items':[{'id':iid,'section':'industry.market','recommended':True}]}
  with pytest.raises(ValueError):import_ai(c,'w1',{**out,'edition_id':'w2'})
  with pytest.raises(ValueError):import_ai(c,'w1',{**out,'input_sha256':'0'*64})
  assert import_ai(c,'w1',{**out,'edition_id':'w1','input_sha256':base['input_sha256']})==1
