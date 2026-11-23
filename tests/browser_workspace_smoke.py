import json,re
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
html=(root/'editor.html').read_text()
html=html.replace('<link rel="stylesheet" href="/assets/editor.css">','<style>'+root.joinpath('assets','editor.css').read_text()+'</style>')
base={'id':'week','title':'테스트 주간호','period_start':'2026-11-16','period_end':'2026-11-22','top_target':4,'status':'draft','issue_number':None,'confirmed_at':None}
rows=[]
for i in range(170):
 rows.append({'id':f'{i:024d}', 'source_key':'dailypharm','source_group':'industry','section':'industry.unclassified','section_override':None,
  'title':f'GLP-1 연구 개발 시장 동향 {i}', 'published_at':'2026-11-18','summary_source':'','url':'https://www.dailypharm.com/user/news/'+str(i),
  'include_detail':0,'top_selected':0,'top_rank':None,'rule_score':34,'verification':'metadata_only','rule_reason':'키워드',
  'rule_section':['industry.policy','industry.market','industry.global','industry.rnd'][i%4],
  'rule_recommended':1,'ai_section':None,'ai_recommended':0,'ai_reason':None,'ai_summary':None,'ai_score':None,'title_override':None,'summary_override':None,'mandatory':0})
state={'edition':base,'week_label':'2026-W47','items':rows,'runs':[],'confirmation':None}
sources={'sources':[{'key':'press','group':'mfds','rss_available':True,'url':'https://www.mfds.go.kr/brd/m_99/list.do'}]}
settings={'sources':[{'key':'press','group':'mfds','url':'https://www.mfds.go.kr/brd/m_99/list.do'}],
 'industry_section_keywords':{'industry.policy':['고시'],'industry.market':['시장']},'ai_api_available':False}
mock='''<script>
const __ed = DATA; const __sources = SOURCES; const __settings = SETTINGS;
window.fetch=async function(path, opts){
 let response = {};
 if(path.startsWith('/api/edition') && !opts && !path.startsWith('/api/editions'))response=__ed;
 else if(path.startsWith('/api/editions'))response={active:'week',editions:[{...__ed.edition}]};
 else if(path.startsWith('/api/sources'))response=__sources;
 else if(path.startsWith('/api/settings'))response=__settings;
 else if(path.startsWith('/api/collection'))response={state:'idle',processed:0,total:0,results:[]};
 else if(path.startsWith('/api/ai/job'))response={state:'idle'};
 else if(path.startsWith('/api/industry/bulk')){response={updated:9,protected:1,not_recommended:0};}
 else if(opts)response={ok:true};
 return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(response))};
};
</script>'''
mock=mock.replace('DATA',json.dumps(state,ensure_ascii=False)).replace('SOURCES',json.dumps(sources,ensure_ascii=False)).replace('SETTINGS',json.dumps(settings,ensure_ascii=False))
html=html.replace('<script>\n\'use strict\';',mock+'<script>\n\'use strict\';')
with sync_playwright() as pl:
 b=pl.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 p=b.new_page(viewport={'width':1380,'height':880});errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
 p.set_content(html,wait_until='load');p.wait_for_function("document.querySelector('#dashCount').textContent.includes('170')",timeout=10000)
 assert p.locator('.view-panel:visible').count()==1
 assert '170건' in p.locator('#dashCount').inner_text()
 p.screenshot(path=str(root/'output'/'workspace_dashboard.png'),full_page=True)
 p.locator('[data-view="edit"]').click();p.wait_for_selector('.item:visible')
 assert p.locator('.item:visible').count()==12
 p.locator('#industrySection').select_option('industry.market')
 assert p.locator('.item:visible').count()==12
 p.screenshot(path=str(root/'output'/'workspace_edit.png'),full_page=True)
 p.locator('[data-view="settings"]').click();assert 'config/sources.yaml' in p.locator('#view-settings').inner_text()
 p.locator('[data-view="preview"]').click();assert p.locator('#confirmedBy').count()==1
 assert not errors,errors
 print('SMOKE PASS desktop, navigation, 170 candidates/12 shown, filters, settings and preview: 0 JS errors')
 m=b.new_page(viewport={'width':390,'height':844});merrors=[];m.on('pageerror',lambda e:merrors.append(str(e)))
 m.set_content(html,wait_until='load');m.wait_for_function("document.querySelector('#dashCount').textContent.includes('170')",timeout=10000)
 m.screenshot(path=str(root/'output'/'workspace_mobile.png'),full_page=True)
 assert not merrors,merrors
 b.close()
