"""Offline Chromium visual smoke test.  Fake fetch only for front-end wiring;
backend collection API is checked separately in test_collection_ui.py.
"""
import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
from playwright.sync_api import sync_playwright

from meditip.collect import import_snapshot, source_specs
from meditip.db import connect, edition_rows, ensure_edition, get_edition, setup
from meditip.edition import prepare

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    with connect(Path(tmp)/'smoke.db') as con:
        setup(con)
        fixture = json.loads((ROOT/'fixtures'/'mfds_2026-11-16_22_partial.json').read_text())
        import_snapshot(con, fixture, 'browser_offline_fixture')
        ensure_edition(con, 'smoke', '2026-11-16', '2026-11-22')
        prepare(con, 'smoke')
        data = {'edition': get_edition(con, 'smoke'), 'items': edition_rows(con, 'smoke'), 'runs': []}

specs = list(source_specs(yaml.safe_load((ROOT/'config'/'sources.yaml').read_text())))
sources = [{'key': s['key'], 'group': s['group'], 'rss_available': bool(s.get('rss_id'))} for s in specs]
html = (ROOT/'editor.html').read_text(encoding='utf8')
html = html.replace('<link rel="stylesheet" href="/assets/editor.css">','<style>'+(ROOT/'assets/editor.css').read_text()+'</style>')
mock = '''<script>
window.__seed = SEED;
window.__sources = SOURCES;
window.__job = {state:'idle',results:[],processed:0,total:0};
window.__collectCalls=0;
window.fetch = async function(path, opts){
 let data={};
 if (!opts) {
   if (path==='/api/edition') data=window.__seed;
   else if(path==='/api/sources') data={sources:window.__sources};
   else if(path==='/api/collection') data=window.__job;
   else if(path==='/api/editions') data={active:'smoke',editions:[window.__seed.edition]};
   else if(path==='/api/ai/job') data={state:'idle'};
   else if(path==='/api/settings') data={sources:[],industry_section_keywords:{},ai_api_available:false};
 } else {
   const body=JSON.parse(opts.body);
   if(path==='/api/top-order'){
     window.__seed.items.forEach(x=>{let i=body.ids.indexOf(x.id);x.top_selected=i>=0?1:0;x.top_rank=i>=0?i+1:null});
   } else if(path==='/api/decision') {
     Object.assign(window.__seed.items.find(x=>x.id===body.item_id),body.changes);
   } else if(path==='/api/target')window.__seed.edition.top_target=body.count;
   else if(path==='/api/collect') {
     window.__collectCalls++;
     window.__job={state:'finished',processed:body.sources.length,total:body.sources.length,
       results:body.sources.map(k=>({source:k,status:'partial',records:2,pages:1,issues:['offline mock']}))};
     data=window.__job;
   } else if(path==='/api/edition/new') {
     window.__seed.edition={...window.__seed.edition,id:'mock-new',period_start:body.start,period_end:body.end};
     data={ok:true,edition_id:'mock-new'};
   }
 }
 return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))};
};
</script>'''
mock=mock.replace('SEED',json.dumps(data,ensure_ascii=False).replace('<','\\u003c')).replace('SOURCES',json.dumps(sources,ensure_ascii=False))
html=html.replace("<script>\n'use strict';",mock+"<script>\n'use strict';")
with sync_playwright() as pl:
    b=pl.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=b.new_page(viewport={'width':1250,'height':870})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content(html,wait_until='load')
    page.locator('[data-view=edit]').click()
    page.locator('[data-queue=all]').click()
    page.wait_for_selector('.queue-row',timeout=6000)
    page.locator('[data-view=collect]').click()
    page.wait_for_selector('#sourceList input',timeout=6000)
    assert page.locator('.queue-row').count()==7
    assert page.locator('#sourceList input').count()>=8
    assert not page.locator('.top-picker').is_visible()
    assert page.locator('.issue-setup #colStart').count()==1
    assert page.locator('.issue-setup #colEnd').count()==1
    assert page.locator('.issue-setup #newEditionId').count()==1
    assert page.locator('.issue-setup #newEditionTitle').count()==1
    assert page.locator('.issue-setup #newEdition').count()==1
    page.locator('#toggleMFDS').click()
    assert page.locator('#sourceList input:checked').count()==8
    assert page.locator('#toggleMFDS').get_attribute('aria-pressed')=='true'
    page.locator('#toggleMFDS').click()
    assert page.locator('#sourceList input:checked').count()==0
    page.locator('#toggleMedia').click()
    assert page.locator('#sourceList input:checked').count()==5
    page.locator('#toggleMedia').click()
    assert page.locator('#sourceList input:checked').count()==0
    page.locator('#toggleMFDS').click()
    assert page.locator('#sourceList input:checked').count()==8
    # Prevent confusing HTTP 400 when the date picker does not match the active edition.
    page.locator('#colStart').fill('2026-11-23')
    page.locator('#colEnd').fill('2026-11-29')
    page.locator('#startCollection').click()
    assert '회차 기간' in page.locator('#collectionResults').inner_text()
    assert page.evaluate('window.__collectCalls')==0
    page.wait_for_timeout(2000)  # collection-status polling must not erase a validation error
    assert '회차 기간' in page.locator('#collectionResults').inner_text()
    page.locator('#colStart').fill('2026-11-16')
    page.locator('#colEnd').fill('2026-11-22')
    page.locator('#colMethod').select_option('rss')
    page.locator('#startCollection').click()
    assert 'RSS가 설정되지 않은 사이트' in page.locator('#collectionResults').inner_text()
    assert page.evaluate('window.__collectCalls')==0
    page.locator('#colMethod').select_option('board')
    page.locator('#startCollection').click()
    page.wait_for_timeout(150)
    assert '수집 작업 종료' in page.locator('#collectionState').inner_text()
    assert page.locator('#collectionResults').is_hidden()  # 2 records/source, partial is not an error log
    assert '후보 16건' in page.locator('#collectionState').inner_text()
    page.evaluate("""() => showCollection({state:'finished',processed:3,total:3,results:[
      {source:'press',status:'partial',records:6,pages:2,issues:['Page coverage unverified']},
      {source:'guides_staff',status:'partial',records:0,pages:1,issues:['No article links parsed']},
      {source:'dailypharm',status:'failed',records:0,pages:0,issues:['HTTPError: 500']}
    ]})""")
    problem=page.locator('#collectionResults')
    assert problem.is_visible()
    assert 'No article links parsed' in problem.inner_text()
    assert 'HTTPError: 500' in problem.inner_text()
    assert 'Page coverage unverified' not in problem.inner_text()
    assert page.evaluate("getComputedStyle(document.querySelector('#collectionResults')).overflowY")=='auto'
    page.evaluate("() => showCollection({state:'finished',edition_id:'previous-week',processed:1,total:1,results:[{source:'guides_staff',status:'failed',records:0}]})")
    assert page.locator('#collectionResults').is_hidden()
    assert '대기' in page.locator('#collectionState').inner_text()
    page.locator('[data-view=edit]').click()
    assert page.locator('.top-picker').is_visible()
    page.locator('[data-view=collect]').click()
    assert page.evaluate('window.__collectCalls')==1
    page.screenshot(path=str(ROOT/'output'/'editor_collection_desktop.png'),full_page=True)
    mobile=b.new_page(viewport={'width':390,'height':844})
    mobile.set_content(html,wait_until='load')
    mobile.locator('[data-view=collect]').click()
    mobile.wait_for_selector('#sourceList input')
    mobile.screenshot(path=str(ROOT/'output'/'editor_collection_mobile.png'),full_page=True)
    assert not errors,errors
    b.close()
print('UI smoke PASS: sources, collection button, mock progress, desktop/mobile rendering')
