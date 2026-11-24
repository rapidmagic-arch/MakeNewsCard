"""Offline browser flow with 208 mock candidates. No external API, no source claims."""
from pathlib import Path
from playwright.sync_api import sync_playwright
import json

ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'editor.html').read_text().replace('<link rel="stylesheet" href="/assets/editor.css">','<style>'+(ROOT/'assets/editor.css').read_text()+'</style>')
base={'id':'demo','title':'모의 주간 편집','period_start':'2026-11-02','period_end':'2026-11-08','top_target':4,'status':'draft','issue_number':None,'confirmed_at':None}
items=[]
for i in range(208):
    ind=i<171
    source='dailypharm' if ind else 'press'
    section='industry.unclassified' if ind else 'mfds.press'
    ai=(ind and i%4 in (0,3))
    ai_rec=bool(ind and i%4==0)
    rule_rec=bool(ind and i%4==1)
    items.append({'id':str(i).zfill(24), 'title':('GLP-1 시장·규제 관련 확인 기사' if ind else '식약처 의약품 관련 공개자료')+f' {i}',
     'source_key':source,'source_group':'industry' if ind else 'mfds','section':section,'section_override':None,
     'published_at':'2026-11-05','summary_source':'원문 메타데이터 요약',
     'url':('https://www.dailypharm.com/user/news/' if ind else 'https://www.mfds.go.kr/brd/m_99/view.do?seq=')+str(10000+i),
     'include_detail':0 if ind else 1,'top_selected':0,'top_rank':None,'rule_score':20,
     'verification':'metadata_only','mandatory':0,'rule_reason':'시장 동향을 고려한 제목 기반 후보',
     'rule_section':'industry.market' if ind else None,'rule_recommended':int(rule_rec),
     'ai_section':('industry.rnd' if ai else None),'ai_recommended':int(ai_rec),'ai_reason':('GPT 시장 관련성 후보' if ai else None),
     'ai_score':60 if ai else None,'ai_relevance':('relevant' if ai_rec else 'irrelevant' if ai else None),
     'ai_summary':'GPT 제안 요약(승인 전)' if ai else None,'title_override':None,'summary_override':None,
     'detail_reviewed':0,'section_reviewed':0})
state={'edition':base,'week_label':'2026-W45','items':items,'runs':[],'run_total':0,'undated_count':0,'out_of_period_count':0,'confirmation':None}
sources={'sources':[{'key':'press','group':'mfds','rss_available':True,'url':'https://www.mfds.go.kr/brd/m_99/list.do'}]}
settings={'sources':[{'key':'press','group':'mfds','url':'https://www.mfds.go.kr/brd/m_99/list.do'}],
'industry_section_keywords':{'industry.policy':['고시'],'industry.market':['시장']},
'review_groups':[{'id':'policy','label':'정책','target_section':'industry.policy','keywords':['고시'],'recommend':True}], 'ai_api_available':False}
mock='''<script>
window.__data = DATA; window.__sources = SOURCES;window.__settings=SETTINGS;window.__calls=[];
window.confirm=()=>true;
window.fetch=async function(path,opts){
  let data={},status=200;
  if(!opts){
    if(path==='/api/edition')data=window.__data;
    else if(path.startsWith('/api/editions'))data={active:'demo',editions:[{...window.__data.edition}]};
    else if(path==='/api/sources')data=window.__sources;
    else if(path==='/api/settings')data=window.__settings;
    else if(path==='/api/collection')data={state:'idle',results:[],processed:0,total:0};
    else if(path==='/api/ai/job')data={state:'idle'};
  }else{
    const body=JSON.parse(opts.body);window.__calls.push({path,body});
    if(path==='/api/industry/bulk'){
      for(const id of body.ids){const row=window.__data.items.find(x=>x.id===id);if(body.mode==='set_inclusion')row.include_detail=body.value?1:0;
       if(body.mode==='apply_sections')row.section_override=row.ai_section||row.rule_section;
       if(body.mode==='apply_recommended'&&(row.ai_recommended||row.rule_recommended)){row.include_detail=1;row.section_override=row.ai_section||row.rule_section;}}
      data={updated:body.ids.length,protected:0,not_recommended:0};
    } else if(path==='/api/decision'){
       Object.assign(window.__data.items.find(x=>x.id===body.item_id),body.changes);data={ok:true};
    }else if(path==='/api/top-order'){
       for(const row of window.__data.items){const pos=body.ids.indexOf(row.id);row.top_selected=pos>=0?1:0;row.top_rank=pos>=0?pos+1:null;}
       data={ok:true};
    }else if(path==='/api/target'){window.__data.edition.top_target=body.count;data={ok:true};}
    else if(path==='/api/ai/review'){data={ok:true,total:body.ids.length};}
    else if(path==='/api/ai/import'){data={analysed:body.items.length};}
    else if(path==='/api/review-groups/save'){
      const list=window.__settings.review_groups;const id=body.id||'custom-1';
      const prev=list.findIndex(x=>x.id===id);const g={...body,id};
      if(prev>=0)list[prev]=g;else list.push(g);data={ok:true,id,groups:list};
    }else if(path==='/api/review-groups/delete'){
      window.__settings.review_groups=window.__settings.review_groups.filter(x=>x.id!==body.id);
      data={ok:true,groups:window.__settings.review_groups};
    }else if(path==='/api/review-groups/recalculate'){data={ok:true,candidates:171};}
    else data={ok:true};
  }
  return {ok:status===200,status,json:async()=>JSON.parse(JSON.stringify(data))};
}
</script>'''
mock=mock.replace('DATA',json.dumps(state,ensure_ascii=False)).replace('SOURCES',json.dumps(sources,ensure_ascii=False)).replace('SETTINGS',json.dumps(settings,ensure_ascii=False))
html=html.replace("<script>\n'use strict';",mock+"<script>\n'use strict';")
with sync_playwright() as pl:
    browser=pl.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1400,'height':900});errs=[];page.on('pageerror',lambda e:errs.append(str(e)))
    page.set_content(html,wait_until='load')
    page.wait_for_function("document.querySelector('#stats').textContent.includes('208')",timeout=9000)
    page.locator('[data-view="edit"]').click();page.wait_for_selector('.queue-row')
    assert '추천 후보' in page.locator('[data-queue="recommended"]').inner_text()
    assert page.locator('.queue-row').count()==12
    assert page.locator('#askQuestion').count()==0
    assert page.locator('#sendQuestion').count()==0
    assert page.locator('#editionScope').is_hidden()
    page.screenshot(path=str(ROOT/'output'/'review_workbench_desktop.png'),full_page=True)
    page.locator('#selectVisible').check()
    assert page.locator('#selectedCount').inner_text()=='선택 12건'
    page.locator('#nextItems').click()
    page.locator('.queue-row:first-child [data-queue-check]').check()
    assert page.locator('#selectedCount').inner_text()=='선택 1건'
    page.locator('#bulkIncludeSelected').click()
    assert page.evaluate("window.__calls.at(-1).body.mode")=='set_inclusion'
    assert page.evaluate("window.__calls.at(-1).body.ids.length")==1
    assert page.locator('#selectedCount').inner_text()=='선택 0건'
    page.locator('[data-queue="included"]').click()
    assert page.locator('#queueTotal').inner_text()=='현재 조건 38건'  # 37 MFDS + 1 newly selected
    # Locate an included industry article regardless of page order and open it.
    page.locator('#group').select_option('industry')
    page.locator('.queue-open').first.click()
    assert '원본 기사' in page.locator('#detailPanel').inner_text()
    assert page.locator('.detail-form').evaluate('(el) => !!(el.compareDocumentPosition(document.querySelector(".original-article")) & Node.DOCUMENT_POSITION_FOLLOWING)')
    assert page.locator('#clearReviewSelection, #bulkApplySections, #applyRecommended').count()==0
    assert 'GPT 요약을 편집란으로 복사' in page.locator('#detailPanel').inner_text()
    assert page.locator('#detailSection').input_value()=='industry.unclassified'  # proposal is not silently approved
    page.locator('#applyAiSummary').click()
    assert page.locator('#detailSummary').input_value()=='GPT 제안 요약(승인 전)'
    page.locator('#saveDetailText').click()
    assert page.evaluate("window.__calls.at(-1).path")=='/api/decision'
    assert not errs,errs
    mobile=browser.new_page(viewport={'width':390,'height':844});mobileerrs=[];mobile.on('pageerror',lambda e:mobileerrs.append(str(e)))
    mobile.set_content(html,wait_until='load');mobile.wait_for_function("document.querySelector('#stats').textContent.includes('208')")
    mobile.locator('[data-view="edit"]').click();mobile.wait_for_selector('.queue-row')
    mobile.screenshot(path=str(ROOT/'output'/'review_workbench_mobile.png'),full_page=True)
    assert mobile.locator('.queue-row').count()==12
    assert mobile.evaluate('document.body.scrollWidth<=window.innerWidth+3'), 'mobile horizontally overflows'
    mobile.locator('.queue-open').first.click()
    assert mobile.locator('#detailPanel').is_visible(), 'detail must open as an overlay on narrow screens'
    assert mobile.evaluate("getComputedStyle(document.querySelector('#detailPanel')).position")=='fixed'
    assert mobile.locator('#detailBackdrop').is_visible()
    mobile.screenshot(path=str(ROOT/'output'/'review_drawer_mobile_v06.png'))
    mobile.locator('#closeDetail').click()
    assert mobile.locator('#detailBackdrop').is_hidden()
    mobile.locator('[data-view="settings"]').click()
    mobile.locator('#reviewGroupName').fill('보험·약가')
    mobile.locator('#reviewGroupTerms').fill('보험급여, 약가')
    mobile.locator('#reviewGroupSection').select_option('industry.policy')
    mobile.locator('#saveReviewGroup').click()
    assert '보험·약가' in mobile.locator('#reviewGroupList').inner_text()
    mobile.screenshot(path=str(ROOT/'output'/'review_groups_settings_mobile_v06.png'),full_page=True)
    mobile.locator('#reviewGroupList [data-group-edit="custom-1"]').click()
    assert mobile.locator('#reviewGroupName').input_value()=='보험·약가'
    mobile.locator('#reviewGroupList [data-group-delete="custom-1"]').click()
    assert '보험·약가' not in mobile.locator('#reviewGroupList').inner_text()
    mobile.locator('#refreshReviewGroups').click()
    assert '재계산' in mobile.locator('#reviewGroupStatus').inner_text()
    assert not mobileerrs,mobileerrs
    medium=browser.new_page(viewport={'width':974,'height':880});mediumerrs=[];medium.on('pageerror',lambda e:mediumerrs.append(str(e)))
    medium.set_content(html,wait_until='load')
    medium.wait_for_function("document.querySelector('#stats').textContent.includes('208')")
    medium.locator('[data-view=edit]').click()
    medium.locator('.queue-open').first.click()
    assert medium.evaluate("getComputedStyle(document.querySelector('#detailPanel')).position")=='fixed'
    assert medium.locator('#detailPanel').is_visible()
    medium.screenshot(path=str(ROOT/'output'/'review_drawer_974_v06.png'))
    assert not mediumerrs,mediumerrs
    browser.close()
print('WORKBENCH SMOKE PASS: 208 candidates, queue tabs, page-scoped selection, single bulk action, no silent AI approval, edit, desktop+mobile')
