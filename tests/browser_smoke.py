"""Browser UI smoke without network: Chromium in this runtime blocks loopback navigation.
The real backend is verified separately via HTTP requests; this test covers JS rendering.
"""
from pathlib import Path
import requests,json
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
seed=requests.get('http://127.0.0.1:8765/api/edition',timeout=5).json()
html=(ROOT/'editor.html').read_text(encoding='utf8')
html=html.replace('<link rel="stylesheet" href="/assets/editor.css">','<style>'+(ROOT/'assets/editor.css').read_text()+'</style>')
patch="""<script>
window.__mock=SEED_HERE;
window.fetch=async function(path,opts){
  if(!opts){return {ok:true,json:async()=>JSON.parse(JSON.stringify(window.__mock))};}
  const body=JSON.parse(opts.body);
  if(path==='/api/top-order'){
    window.__mock.items.forEach(x=>{let i=body.ids.indexOf(x.id);x.top_selected=i>=0?1:0;x.top_rank=i>=0?i+1:null});
  }else if(path==='/api/decision'){
    Object.assign(window.__mock.items.find(x=>x.id===body.item_id),body.changes)
  }else if(path==='/api/target'){window.__mock.edition.top_target=body.count}
  return {ok:true,json:async()=>({ok:true})}
}
</script>""".replace('SEED_HERE',json.dumps(seed,ensure_ascii=False).replace('<','\\u003c'))
html=html.replace('<script>\n\'use strict\';',patch+'\n<script>\n\'use strict\';')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1280,'height':900},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content(html,wait_until='load')
    page.locator('[data-view=edit]').click()
    page.wait_for_selector('.item',timeout=10000)
    assert page.locator('.item').count()==7
    page.screenshot(path=str(ROOT/'output'/'editor_desktop.png'),full_page=True)
    top_before=page.locator('.rankrow').count()
    checkbox=page.locator('.item').last.locator('[data-kind=top]')
    changed=not checkbox.is_checked()
    checkbox.set_checked(changed)
    page.wait_for_timeout(250)
    assert page.locator('.rankrow').count()==top_before+(1 if changed else -1)
    mobile=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
    mobile.set_content(html,wait_until='load')
    mobile.locator('[data-view=edit]').click()
    mobile.wait_for_selector('.item')
    mobile.screenshot(path=str(ROOT/'output'/'editor_mobile.png'),full_page=True)
    assert not errors,errors
    print('BROWSER UI PASS: 7 candidates, first-pass TOP',top_before,'checkbox interaction, desktop/mobile screenshots')
    browser.close()
