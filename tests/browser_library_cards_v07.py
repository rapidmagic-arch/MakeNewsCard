"""Offline Playwright smoke: archive paging and optional article card navigation."""
from pathlib import Path
from meditip.ui_assets import read_editor
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
html=read_editor(ROOT/'editor.html',inline_script=True).replace(
    '<link rel="stylesheet" href="/assets/editor.css">',
    '<style>'+(ROOT/'assets/editor.css').read_text(encoding='utf8')+'</style>')
edition={'id':'demo','title':'편집 중','period_start':'2026-11-02','period_end':'2026-11-08',
         'status':'draft','top_target':4,'issue_number':None,'confirmed_at':None}
items=[]
for n in range(2):
    items.append({'id':str(n),'source_key':'dailypharm','source_group':'industry',
      'title':'시장 허가 관련 기사 '+str(n),'section':'industry.unclassified',
      'published_at':'2026-11-03','url':'https://www.dailypharm.com/user/news/'+str(100+n),
      'verification':'metadata_only','summary_source':'','rule_recommended':True,
      'rule_reason':'시장 허가','rule_section':'industry.policy','rule_group_id':None,
      'ai_score':None,'ai_reason':None,'ai_section':None,'ai_summary':None,'ai_recommended':None,
      'include_detail':0,'top_selected':0,'top_rank':None,'mandatory':0,
      'section_override':None,'title_override':None,'summary_override':None})
data={'edition':edition,'week_label':'2026-W45','items':items,'runs':[],
      'run_total':0,'undated_count':0,'out_of_period_count':0}
archive=[{'id':'issue-'+str(i),'title':'주간 뉴스레터 '+str(i),'status':'confirmed',
          'period_start':'2026-11-02','period_end':'2026-11-08','issue_number':str(800+i),
          'confirmed_at':'2026-11-24','candidates':25,'included':8} for i in range(15)]
settings={'sources':[],'review_groups':[],'ai_api_available':False}
shim='''<script>
window.__edition=DATA;window.__archive=ARCHIVE;window.__settings=SETTINGS;
window.fetch=async (path,opts)=>{
  let value={};
  if(!opts){
    const u=new URL(path,'http://localhost');
    if(u.pathname==='/api/library'){
      const page=+(u.searchParams.get('page')||1),query=u.searchParams.get('q')||'';
      const rows=window.__archive.filter(x=>x.title.includes(query));
      value={total:rows.length,page,pages:Math.ceil(rows.length/12),items:rows.slice((page-1)*12,page*12)};
    }else if(path==='/api/edition')value=window.__edition;
    else if(path==='/api/editions')value={active:'demo',editions:[window.__edition.edition]};
    else if(path==='/api/settings')value=window.__settings;
    else if(path==='/api/sources')value={sources:[]};
    else if(path==='/api/collection')value={state:'idle',results:[],processed:0,total:0};
    else if(path==='/api/ai/job')value={state:'idle'};
  }else value={ok:true};
  return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(value))};
}
</script>'''
shim=shim.replace('DATA',json.dumps(data,ensure_ascii=False))
shim=shim.replace('ARCHIVE',json.dumps(archive,ensure_ascii=False))
shim=shim.replace('SETTINGS',json.dumps(settings,ensure_ascii=False))
html=html.replace("<script>\n'use strict';",shim+"<script>\n'use strict';")
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1280,'height':900});errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content(html,wait_until='load')
    page.wait_for_function("document.querySelectorAll('.library-card').length===12")
    assert page.locator('#openEditionDialog').is_hidden()
    page.locator('#libraryNext').click()
    assert page.locator('.library-card').count()==3
    page.locator('[data-view=edit]').click()
    assert page.locator('#openEditionDialog').is_visible()
    page.locator('#openEditionDialog').click()
    assert page.locator('#editionDialog').is_visible()
    page.locator('#closeEditionDialog').click()
    page.locator('#viewModeToggle').click()
    assert page.locator('#cardGallery').is_visible()
    page.locator('#cardNext').click()
    assert '2 / 2' in page.locator('#cardStatus').inner_text()
    page.locator('#featuredArticle [data-open-id]').click()
    assert '원본 기사' in page.locator('#detailPanel').inner_text()
    assert not errors, errors
    browser.close()
print('Archive and candidate-card browser smoke passed')
