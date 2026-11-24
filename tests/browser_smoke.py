"""Offline Chromium smoke: historical sample, explicit TOP selection."""
import json,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from meditip.db import connect,setup,ensure_edition,get_edition,edition_rows
from meditip.collect import import_snapshot
from meditip.edition import prepare
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as d:
    with connect(Path(d)/'smoke.db') as con:
        setup(con)
        import_snapshot(con,json.loads((ROOT/'fixtures'/'mfds_2026-11-16_22_partial.json').read_text()),'offline')
        ensure_edition(con,'smoke','2026-11-16','2026-11-22')
        prepare(con,'smoke')
        data={'edition':get_edition(con,'smoke'),'items':edition_rows(con,'smoke'),
              'week_label':'2026-W47','runs':[],'run_total':0,'undated_count':0,'out_of_period_count':0}
html=(ROOT/'editor.html').read_text().replace('<link rel="stylesheet" href="/assets/editor.css">',
    '<style>'+(ROOT/'assets/editor.css').read_text()+'</style>')
mock='''<script>
window.__seed=PAYLOAD;
window.fetch=async(path,opts)=>{
 let data={};
 if(!opts){
  if(path==='/api/edition')data=window.__seed;
  if(path==='/api/editions')data={active:'smoke',editions:[window.__seed.edition]};
  if(path==='/api/sources')data={sources:[]};
  if(path==='/api/settings')data={sources:[],industry_section_keywords:{},ai_api_available:false};
  if(path==='/api/collection'||path==='/api/ai/job')data={state:'idle',processed:0,total:0,results:[]};
 }else if(path==='/api/top-order'){
  const body=JSON.parse(opts.body);
  for(const x of window.__seed.items){const i=body.ids.indexOf(x.id);x.top_selected=i<0?0:1;x.top_rank=i<0?null:i+1;}
  window.__seed.top_output_ids=body.ids.slice(0,window.__seed.edition.top_target);
  data={ok:true};
 }else data={ok:true};
 return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(data))}
};
</script>'''.replace('PAYLOAD',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
html=html.replace("<script>\n'use strict';",mock+"<script>\n'use strict';")
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1280,'height':900})
    err=[];page.on('pageerror',lambda e:err.append(str(e)))
    page.set_content(html,wait_until='load')
    page.locator('[data-view=edit]').click()
    page.locator('[data-queue=all]').click()
    page.wait_for_selector('.queue-row',timeout=10000)
    assert page.locator('.queue-row').count()==7
    page.locator('.queue-open').first.click()
    count=page.locator('#top .rankrow').count()
    page.locator('#detailTop').check()
    page.wait_for_timeout(200)
    assert page.locator('#top .rankrow').count()==count+1
    assert page.locator('.queue-row.active .tag-top').inner_text()=='TOP 1 · 출력'
    page.locator('[data-view=preview]').click()
    assert '주요 뉴스 1건 출력' in page.locator('#previewTopState').inner_text()
    assert not err,err
    browser.close()
print('Browser smoke PASS: 7 sample records and 1 explicit TOP selection')
