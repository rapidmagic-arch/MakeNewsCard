"""Newsletter 892-style renderer. No personalized mailing links are retained."""
from html import escape
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs
from bs4 import BeautifulSoup
from .db import edition_rows,get_edition

GROUPS={'mfds.guides':'공무원지침서/민원인안내서',
        'mfds.regulations':'입법·행정예고 / 제개정고시 / 법령',
        'mfds.press':'보도자료','mfds.notices':'공지/공고',
        'industry.policy':'정책','industry.market':'시장',
        'industry.global':'글로벌','industry.rnd':'연구/개발','industry.unclassified':'미분류 · 담당자 검토 필요'}


def txt(x):return escape(str(x or ''))

def effective(row,key):
    if key=='title':return row.get('title_override') if row.get('title_override') is not None else row['title']
    if key=='summary':
        return (row.get('summary_override') if row.get('summary_override') is not None else
                row.get('summary_source',''))
    if key=='section':return row.get('section_override') or row['section']
    return row.get(key)

def link(x):
    from urllib.parse import urlsplit
    url=x['url']
    if urlsplit(url).scheme not in ('http','https'):return txt(effective(x,'title'))
    return f'<a style="color:#1c3854;text-decoration:underline" href="{escape(url,quote=True)}">{txt(effective(x,"title"))}</a>'

def _display_identity(row):
    url=urlsplit(row.get('url') or '')
    if row.get('source_group')=='mfds' and url.hostname=='www.mfds.go.kr':
        board=re.search(r'/brd/m_(\d+)/view\.do$',url.path)
        seq=parse_qs(url.query).get('seq',[None])[0]
        if board and seq:return ('mfds',board.group(1),seq)
    title=re.sub(r'\s+',' ',row.get('title') or '').strip().casefold()
    if title and row.get('published_at'):
        return ('headline',row.get('source_key'),row['published_at'],title)
    return ('id',row['id'])


def unique_for_display(items):
    seen=set()
    for row in items:
        key=_display_identity(row)
        if key in seen:continue
        seen.add(key)
        yield row


MFDS_BOARD_SECTION={
    '1059':'mfds.guides','1060':'mfds.guides',
    '209':'mfds.regulations','207':'mfds.regulations','203':'mfds.regulations',
    '99':'mfds.press','74':'mfds.notices','76':'mfds.notices',
}


def mfds_unique_sectioned(rows):
    groups={}
    for row in rows:
        if not row['include_detail'] or row['source_group']!='mfds':continue
        key=_display_identity(row)
        groups.setdefault(key,[]).append(row)
    for variants in groups.values():
        def priority(row):
            canonical=_display_identity(row)
            board=canonical[1] if canonical[0]=='mfds' else None
            actual=MFDS_BOARD_SECTION.get(board)
            return (int(bool(row.get('section_override'))),
                    int(bool(actual) and row['section']==actual),
                    int(bool(row['mandatory'])))
        row=max(variants,key=priority)
        board_id=_display_identity(row)
        expected=MFDS_BOARD_SECTION.get(board_id[1]) if board_id[0]=='mfds' else None
        section=row.get('section_override') or expected or row['section']
        yield row,section


SOURCE_NAMES={'dailypharm':'데일리팜','medisobizanews':'메디소비자뉴스','medicaltimes':'메디칼타임즈','kpanews':'약사공론','yakup':'약업신문','company_manual':'메디팁 등록 자료'}

def source_name(row):
    if row.get('source_group')=='company':
        import json
        return (json.loads(row.get('original_metadata') or '{}').get('publisher') or SOURCE_NAMES.get(row['source_key'],row['source_key']))
    return SOURCE_NAMES.get(row['source_key'],row['source_key'])

def company_cards(items):
    cards=[]
    for x in unique_for_display(items):
        summary=txt(effective(x,'summary'))
        cards.append('<tr><td style="padding:10px;border:1px solid #d3dce5;font:13px/1.6 Malgun Gothic,Arial,sans-serif">'+link(x)+'<br><span style="font-size:11px;color:#526477">'+txt(source_name(x))+'</span>'+('<p style="margin:4px 0">'+summary+'</p>' if summary else '')+'</td></tr>')
    return '<table role="presentation" width="100%" cellspacing="0" cellpadding="0">'+''.join(cards)+'</table>' if cards else ''

def list_html(items,group,final=False):
    res=[]
    for x in unique_for_display(items):
        label=txt(x.get('published_at') or '날짜 미확인') if group=='mfds' else txt(source_name(x))
        res.append('<span style="display:block;padding:2px 0;line-height:1.45;font-size:12px;overflow-wrap:anywhere" data-record-id="'+txt(x['id'])+'">'
                   +label+'　'+link(x)+'</span>')
    return ''.join(res) or ('' if final else '<span style="color:#8a5962;font-size:12px">확인된 수록 자료 없음 (수집 완료 여부 별도 확인)</span>')

def group_html(rows,group,final=False):
    parts=[]
    mfds_items=list(mfds_unique_sectioned(rows)) if group=='mfds' else []
    keys=[x for x in GROUPS if x.startswith(group+'.') and x!='industry.unclassified']
    if group=='industry' and any(x['include_detail'] and effective(x,'section')=='industry.unclassified' for x in rows):
        keys.append('industry.unclassified')
    for key in keys:
        items=([x for x,section in mfds_items if section==key] if group=='mfds'
               else [x for x in rows if x['include_detail'] and effective(x,'section')==key])
        if final and not items: continue
        parts.append('<span style="display:block;margin:15px 0 7px;color:#2980b9;font-size:16px;font-weight:bold">'+txt(GROUPS[key])+'</span>')
        parts.append(list_html(items,group,final))
    if group=='industry' and not final:
        candidates=[x for x in rows if x['source_group']=='industry']
        if candidates and not any(x['include_detail'] for x in candidates):
            parts.insert(0,'<span style="display:block">언론기사 후보 '+str(len(candidates))+'건이 있지만 상세 수록으로 선택되지 않았어. 편집 화면에서 수록 여부와 섹션을 확인해.</span>')
        elif not candidates:
            parts.insert(0,'<span style="display:block">이 회차에 등록된 언론기사 후보가 없어. 수집 상태를 확인해 (전체 0건 의미 아님).</span>')
    return ''.join(parts)

def approval_table(items,kind,final=False):
    import json
    fields={'clinical':['의뢰자','제품명','임상시험제목','임상시험 단계','승인일'],
            'treatment':['신청인','제품명','대상질환','승인일'],
            'drug':['제품명','업체명','허가일']}[kind]
    if not items:return ''
    parts=['<table role="presentation" width="100%" cellpadding="4" cellspacing="0" border="1" style="border-collapse:collapse;border:1px solid #c5d4df;font:11px/1.5 Malgun Gothic,Arial,sans-serif">',
           '<thead><tr>'+''.join('<th style="background:#e5eff8;color:#123953">'+txt(x)+'</th>' for x in fields)+'</tr></thead><tbody>']
    for r in items:
        raw=json.loads(r.get('original_metadata') or '{}').get('csv_row') or {}
        vals=[]
        for f in fields:
            aliases={'승인일':['승인일자','허가일','허가일자'],'허가일':['허가일자','승인일','승인일자'],'임상시험제목':['임상시험 제목'],
                     '임상시험 단계':['임상시험단계','단계'], '제품명':['품목명','제품명칭']}
            value=raw.get(f) or next((raw.get(x) for x in aliases.get(f,[]) if raw.get(x)),None)
            if not value and f in ('임상시험제목','제품명'):value=r['title']
            if not value and f in ('승인일','허가일'):value=r.get('published_at')
            vals.append('<td style="padding:6px;vertical-align:top">'+txt(value or '—')+'</td>')
        parts.append('<tr>'+''.join(vals)+'</tr>')
    parts.append('</tbody></table>')
    if not final:
        parts.append('<p style="font-size:11px;color:#986b43">담당자 제공 CSV 기준 · 공식 원본 건수·데이터 정확성은 미검증</p>')
    return ''.join(parts)


def top_output_rows(rows, target):
    """Rank selected candidates, preserve decisions, and cap unique output."""
    ranked = sorted((r for r in rows if r['top_selected']),
                    key=lambda r: (r['top_rank'] if r['top_rank'] is not None else 9999, r['id']))
    return list(unique_for_display(ranked))[:max(0, int(target))]


def top_table(items):
    items=list(unique_for_display(items))
    if not items:return '<p style="padding:16px;color:#8a5962;font-size:13px">주요 뉴스 선정 대기</p>'
    result=['<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="border-collapse:collapse">']
    for i in range(0,len(items),2):
        result.append('<tr>')
        for x in items[i:i+2]:
            summary=txt(effective(x,'summary'))
            result.append('<td width="50%" valign="top" style="padding:5px">'
                          '<div style="border:1px solid #d3dce5;padding:11px;font:13px/1.6 Malgun Gothic,Arial,sans-serif;overflow-wrap:anywhere">'
                          +link(x)+ ('<p style="margin:7px 0 0;color:#343b45;font-size:12px">'+summary+'</p>' if summary else '')+'</div></td>')
        if i+1>=len(items):result.append('<td width="50%"></td>')
        result.append('</tr>')
    result.append('</table>')
    return ''.join(result)

def render(con,edition_id,template_path,final=False,preview=False,template_id=None):
    from .mail_templates import validate_template_id, render_outlook_cards
    edition=get_edition(con,edition_id)
    selected=validate_template_id(template_id or edition.get('template_id') or 'classic')
    if selected=='outlook_cards':
        return render_outlook_cards(con,edition_id,final=final,preview=preview)
    from .company import company_output_rows
    rows=edition_rows(con,edition_id)
    publish_view=final or preview
    if publish_view:
        # AI summaries are proposals until saved explicitly by a human.
        for row in rows:
            if row.get('summary_override') is None:
                row['ai_summary']=None
    tops=top_output_rows(rows, edition['top_target'])
    soup=BeautifulSoup(Path(template_path).read_text(encoding='utf-8'),'html.parser')
    from .branding import get_branding, default_banner, contact_lines
    branding=get_branding(con)
    for slot,src,width in (('logo',branding.get('logo',''),320),('banner',branding.get('banner') or default_banner(template_path),800)):
        node=soup.select_one('[data-image-slot="'+slot+'"]')
        if node is not None and src:
            img=soup.new_tag('img',src=src,alt='MEDiTIP 뉴스레터 '+('MVP 이미지' if slot=='banner' and not branding.get('banner') else slot),width=str(width))
            img['style']='display:block;width:100%;max-width:'+str(width)+'px;height:auto;border:0'
            node.clear()
            node.append(img)
    contact=soup.select_one('[data-contact-slot]')
    if contact:
        contact.clear()
        for line in ['MEDiTIP 뉴스레터 · 의약품 시장 정보 제공']+contact_lines(branding):
            if contact.contents:contact.append(soup.new_tag('br'))
            contact.append(line)
    first=soup.select_one('#i8voq4');second=soup.select_one('#icsna')
    if not first or not second:raise ValueError('Original 892 TOP layout markers not found')
    first.replace_with(BeautifulSoup(top_table(tops),'html.parser'))
    second.decompose()
    replacements={
       'company_news':company_cards(company_output_rows(rows)),
       'mfds_all':group_html(rows,'mfds',publish_view),
       'industry_all':group_html(rows,'industry',publish_view)}
    for name,content in replacements.items():
        node=soup.select_one('[data-slot="'+name+'"]')
        if not node:raise ValueError('Required HTML slot missing: '+name)
        node.clear()
        if content:node.append(BeautifulSoup(content,'html.parser'))
    title=soup.title
    issue_label=('제'+edition['issue_number']+'호') if edition.get('issue_number') else edition['title']
    if not title and soup.head:
        title=soup.new_tag('title')
        soup.head.append(title)
    if title:title.string='MEDiTIP 뉴스레터 - '+issue_label+('' if final else ' [미확정 미리보기]' if preview else ' [검토용]')
    banner=soup.find(string=lambda s:s and 'MEDITIP MVP 테스트' in s)
    if banner:
        banner.replace_with(('MEDiTIP 뉴스레터 · '+issue_label) if publish_view else ('MEDiTIP 뉴스레터 편집 초안 · '+edition['title']+' · 외부 발송 금지'))
    for slot, groups in (('clinical', ('clinical','treatment')), ('drug', ('drug',))):
        node=soup.select_one('[data-approval-slot="'+slot+'"]')
        if node is None:raise ValueError('Missing approval slot: '+slot)
        node.clear()
        for kind in groups:
            selected_rows=[r for r in rows if r['source_group']==kind and r['include_detail']]
            if selected_rows:
                if kind=='treatment':
                    node.append(BeautifulSoup('<p style="color:#2980b9;font-weight:bold">치료목적 사용승인</p>','html.parser'))
                node.append(BeautifulSoup(approval_table(selected_rows,kind,publish_view),'html.parser'))
        if not node.get_text(strip=True) and not publish_view:
            node.string='등록된 승인·허가 자료 없음'
    for slot, heading in (('company-heading','이번 호 Meditip 주요 소식'),
                          ('industry-heading','한 주간 제약 산업 및 제도 업데이트 ('+edition['period_start']+' ~ '+edition['period_end']+')')):
        node=soup.select_one('[data-heading-slot="'+slot+'"]')
        if node:
            node.clear()
            node.append(BeautifulSoup('<strong style="font: bold 19px Malgun Gothic,Arial,sans-serif;color:#2980b9">'+txt(heading)+'</strong>','html.parser'))
    for anchor in soup.find_all('a',href=True):
        if anchor['href'].startswith('https://nedrug.mfds.go.kr/searchClinic'):
            anchor['href']='https://nedrug.mfds.go.kr/searchClinic'
    # Original 892 issue date/number is historic; it must not imply a new issued newsletter.
    for t in list(soup.find_all(string=True)):
        val=str(t)
        if '892호' in val and '발간수기' in val:
            t.replace_with('MEDiTIP 뉴스레터 · '+issue_label)
        elif '11월' in val and '둘째 주' in val:
            if 'Meditip 주요' in val:
                t.replace_with('이번 호 Meditip 주요 소식')
            elif '산업' in val and '업데이트' in val:
                t.replace_with('제약 산업 및 제도 업데이트 ('+edition['period_start']+' ~ '+edition['period_end']+')')
        elif 'Copyright2015' in val:
            t.replace_with('MEDiTIP 뉴스레터' if final else 'MEDiTIP · 편집용 템플릿 / 법인 정보 확인 필요')
    for a in soup.find_all('a',href=True):
        if a.get('href','').strip()=='#':
            a.decompose() if publish_view else a.replace_with(BeautifulSoup('<span style="color:#607588">'+txt(a.get_text(' ',strip=True))+' (발송 시스템에서 설정)</span>','html.parser'))
    if publish_view:
        for td in list(soup.select('td')):
            if '메일 수신을 원치 않으시면' in td.get_text(' ',strip=True):td.decompose()
        for t in list(soup.find_all(string=True)):
            if any(marker in str(t) for marker in ('[원본 로고 이미지','[원본 배너 이미지','[담당자 연락처]','[담당자 이메일]','[수신거부]','[unsubscription]')):
                t.replace_with('')
    publication=soup.select_one('[data-publication-slot]')
    if publication:
        publication.string=' · '.join(x for x in (issue_label, ('발행일 '+edition['publication_date']) if edition.get('publication_date') else '', '수집 기간 '+edition['period_start']+' ~ '+edition['period_end']) if x)
    html=str(soup)
    if '{{' in html and '}}' in html:raise ValueError('Unresolved template slots remain')
    return html
