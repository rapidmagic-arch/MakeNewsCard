"""Real localhost browser regression; no external source or GPT calls."""
import socket
import tempfile
import threading
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright, expect
from meditip.db import connect,setup,ensure_edition,save_item
from meditip.edition import prepare
import meditip.server as server
from meditip.approval_live import parse_approval_page,approval_url

ROOT=Path(__file__).resolve().parents[1]

def offline_official(kind,start,end):
    if kind!='treatment':raise ValueError('test source unavailable')
    content=(ROOT/'fixtures/approval_treatment_20261116_page1.html').read_bytes()
    total,rows=parse_approval_page(content,kind,start,end)
    return dict(total=total,pages=1,rows=rows,query_url=approval_url(kind,start,end))
server.fetch_approval=offline_official
server.fetch_medicaltimes_detail=lambda url:{'title':'메디팁 시장 테스트 기사','published_at':'2026-11-17'}
with tempfile.TemporaryDirectory() as tmp:
    db=Path(tmp)/'browser.db'
    with connect(db) as con:
        setup(con)
        ensure_edition(con,'week','2026-11-16','2026-11-22')
        save_item(con,dict(source_key='medicaltimes',source_group='industry',section='industry.unclassified',
          title='메디팁 시장 테스트 기사 [메디칼타임즈=기자] 본문 2026-11-17 10:00:00',url='https://www.medicaltimes.com/Main/News/NewsView.html?ID=9123',
          published_at='2026-11-17'))
        con.commit();prepare(con,'week')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    threading.Thread(target=server.serve,args=(db,ROOT/'templates/892_slots_original.html',ROOT/'editor.html','week',port),daemon=True).start()
    base=f'http://127.0.0.1:{port}'
    for _ in range(100):
        try:
            if requests.get(base,timeout=1).ok:break
        except requests.RequestException:time.sleep(.03)
    else:raise AssertionError('local editor unavailable')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':900})
        errors=[]
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.on('dialog',lambda dialog:dialog.accept())
        page.goto(base)
        page.locator('[data-view=edit]').click()
        page.locator('[data-queue=all]').click()
        expect(page.locator('.queue-row')).to_have_count(1)
        expect(page.locator('#headerEdition')).to_contain_text('편집 가능 · 초안')
        expect(page.locator('#selectVisible')).to_be_enabled()
        page.locator('#selectVisible').check()
        expect(page.locator('#selectedCount')).to_have_text('선택 1건')
        page.locator('.queue-row [data-queue-check]').uncheck()
        expect(page.locator('#selectedCount')).to_have_text('선택 0건')
        page.locator('#viewModeToggle').click()
        page.locator('[data-card-select]').check()
        expect(page.locator('#selectedCount')).to_have_text('선택 1건')
        page.locator('[data-card-select]').uncheck()
        page.locator('#viewModeToggle').click()
        page.locator('#qualityFilter').select_option('title')
        expect(page.locator('.queue-row')).to_have_count(1)
        expect(page.locator('.queue-chips .tag.warn')).to_have_text('제목 확인')
        page.locator('.queue-open').first.click()
        expect(page.locator('.original-heading .original-link')).to_have_attribute('href','https://www.medicaltimes.com/Main/News/NewsView.html?ID=9123')
        expect(page.locator('.detail-title .original-link')).to_be_visible()
        page.locator('#recheckMetadata').click()
        expect(page.locator('#recheckStatus')).to_contain_text('원본 메타데이터 갱신')
        expect(page.locator('.source-title')).to_have_text('메디팁 시장 테스트 기사')
        expect(page.locator('.queue-row')).to_have_count(0)
        page.locator('#qualityFilter').select_option('all')
        page.locator('#detailCompany').check()
        expect(page.locator('#companyList')).to_contain_text('메디팁 시장 테스트 기사')
        page.locator('#detailTop').check()
        expect(page.locator('.queue-row.active .tag-top')).to_have_text('TOP 1 · 출력')
        page.locator('#closeDetail').click()
        page.locator('summary').filter(has_text='회사 소식 등록').click()
        page.locator('#companyTitle').fill('직접 등록 회사 소식')
        page.locator('#companyPublisher').fill('담당자 자료')
        page.locator('#companyUrl').fill('https://example.org/company')
        page.locator('#companyDate').fill('2026-11-18')
        page.locator('#companySummary').fill('승인된 회사 소식 요약')
        page.locator('#saveCompany').click()
        expect(page.locator('#companyStatus')).to_have_text('등록 완료')
        expect(page.locator('#companyList .rankrow')).to_have_count(2)
        first_id=page.locator('#companyList [data-company-open]').first.get_attribute('data-company-open')
        page.locator('#companyList [data-company-move="1"]').first.click()
        expect(page.locator('[data-queue=company]')).to_have_attribute('aria-selected','true')
        expect(page.locator('.queue-row').nth(1)).to_have_attribute('data-id',first_id)
        expect(page.locator('.queue-row').nth(1).locator('.tag-rule').last).to_have_text('회사 소식 2')
        page.locator('[data-view=collect]').click()
        page.locator('[data-source=press]').uncheck()
        page.locator('[data-source=dailypharm]').check()
        page.reload()
        page.locator('[data-view=collect]').click()
        expect(page.locator('[data-source=press]')).not_to_be_checked()
        expect(page.locator('[data-source=dailypharm]')).to_be_checked()
        expect(page.locator('#mediaRights')).not_to_be_checked()
        page.locator('#approvalKind').select_option('drug')
        page.locator('[data-drop-input="approvalFile"]').evaluate("""zone=>{const data=new DataTransfer();data.items.add(new File(['품목명,업체명,허가일자\\nBrowser-Drug,Maker,2026-11-20\\n'],'approval.csv',{type:'text/csv'}));zone.dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true}))}""")
        expect(page.locator('[data-drop-input="approvalFile"] .drop-filename')).to_contain_text('approval.csv')
        page.locator('#importApproval').click()
        expect(page.locator('#approvalStatus')).to_contain_text('등록 1건')
        page.locator('#approvalKind').select_option('treatment')
        page.locator('#collectApproval').click()
        expect(page.locator('#approvalStatus')).to_contain_text('공식 조회 4건',timeout=15000)
        expect(page.locator('#approvalStatus')).to_contain_text('등록 4건')
        page.locator('#collectAllApprovals').click()
        expect(page.locator('#approvalStatus')).to_contain_text('성공 1 · 실패 2',timeout=15000)
        expect(page.locator('#collectionResults')).to_contain_text('공식 조회 4건')
        expect(page.locator('#collectionResults')).to_contain_text('test source unavailable')
        expect(page.locator('#collectionResults')).to_contain_text('다른 방식')
        page.screenshot(path=str(ROOT/'output'/'v012_approval_desktop.png'),full_page=True)
        page.locator('[data-view=settings]').click()
        expect(page.locator('#brandingImages')).to_contain_text('MVP 이미지')
        expect(page.locator('#brandContact')).to_have_value('최서영')
        expect(page.locator('#brandEmail')).to_have_value('sychoi@meditip.co.kr')
        assert page.locator('#brandPhone').evaluate('el=>el.getBoundingClientRect().height')>=40
        assert page.locator('#resetLogo').evaluate('el=>el.getBoundingClientRect().width')==18
        page.screenshot(path=str(ROOT/'output'/'v012_branding_desktop.png'),full_page=True)
        page.locator('#brandContact').fill('Browser Test Contact')
        page.locator('#brandEmail').fill('review@example.org')
        page.locator('#saveBranding').click()
        expect(page.locator('#brandingStatus')).to_contain_text('저장 완료')
        assert requests.get(base+'/api/settings',timeout=3).json()['branding']['contact_name']=='Browser Test Contact'
        page.locator('[data-view=preview]').click()
        page.locator('#issueNumber').fill('901')
        page.locator('#publicationDate').fill('2026-11-25')
        page.locator('#savePublication').click()
        expect(page.locator('#confirmMessage')).to_contain_text('저장 완료')
        expect(page.locator('#previewTopState')).to_contain_text('주요 뉴스 1건 출력')
        expect(page.locator('#templateChoice option[value=classic]')).to_have_text('뉴스카드 양식 v01')
        expect(page.locator('#templateChoice option[value=outlook_cards]')).to_have_text('아웃룩 양식 v01')
        frame=page.frame_locator('#newsletterPreview')
        expect(frame.locator('[data-slot="company_news"]')).to_contain_text('직접 등록 회사 소식')
        expect(frame.locator('[data-approval-slot="drug"]')).to_contain_text('Browser-Drug')
        expect(frame.locator('[data-approval-slot="clinical"]')).to_contain_text('방광암')
        expect(frame.locator('[data-publication-slot]')).to_contain_text('발행일 2026-11-25')
        expect(frame.locator('[data-contact-slot]')).to_contain_text('Browser Test Contact')
        expect(frame.locator('[data-image-slot="banner"] img')).to_have_js_property('naturalWidth',1600)
        expect(frame.locator('[data-image-slot="footer"] img')).to_have_js_property('naturalWidth',1600)
        assert frame.locator('[data-contact-slot]').evaluate('el=>el.getBoundingClientRect().bottom<=el.parentElement.nextElementSibling.getBoundingClientRect().top+1')
        page.locator('#confirmedBy').fill('Test Operator')
        page.locator('#finalAck').check()
        page.locator('#confirmIssue').click()
        expect(page.locator('#finalState')).to_contain_text('확정본')
        expect(page.locator('#confirmIssue')).to_be_disabled()
        expect(page.locator('#headerEdition')).to_contain_text('확정 · 읽기 전용')
        page.locator('[data-view=edit]').click()
        expect(page.locator('#selectVisible')).to_be_disabled()
        page.locator('#group').select_option('industry')
        expect(page.locator('[data-queue-check]')).to_be_disabled()
        page.locator('.queue-open').first.click()
        expect(page.locator('#detailTop')).to_be_checked()
        expect(page.locator('#detailTop')).to_be_disabled()
        expect(page.locator('#detailCompany')).to_be_checked()
        expect(page.locator('#detailCompany')).to_be_disabled()
        page.locator('#closeDetail').click()
        page.locator('#viewModeToggle').click()
        expect(page.locator('[data-card-select]')).to_be_disabled()
        page.locator('#viewModeToggle').click()
        expect(page.locator('#openDraftSetup')).to_be_visible()
        frozen=requests.get(base+'/export/html',timeout=3).content
        assert b'Browser-Drug' in frozen
        page.locator('[data-view=settings]').click()
        page.locator('#brandContact').fill('Changed Contact')
        page.locator('#saveBranding').click()
        expect(page.locator('#brandingStatus')).to_contain_text('저장 완료')
        assert requests.get(base+'/api/settings',timeout=3).json()['branding']['contact_name']=='Changed Contact'
        assert requests.get(base+'/export/html',timeout=3).content==frozen
        mobile=browser.new_page(viewport={'width':390,'height':844})
        mobile.goto(base)
        mobile.locator('[data-view=settings]').click()
        expect(mobile.locator('#brandContact')).to_have_value('Changed Contact')
        assert mobile.evaluate('document.body.scrollWidth<=window.innerWidth+3')
        mobile.screenshot(path=str(ROOT/'output'/'v012_branding_mobile.png'),full_page=True)
        assert not errors,errors
        browser.close()
print('v0.11 localhost browser: company, TOP, CSV, branding, publication and frozen HTML PASS')
