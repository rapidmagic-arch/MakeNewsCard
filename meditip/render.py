"""Newsletter 892-style renderer. No personalized mailing links are retained."""
from html import escape
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from bs4 import BeautifulSoup
from .db import edition_rows,get_edition

GROUPS={'mfds.guides':'공무원지침서/민원인안내서',
        'mfds.regulations':'입법·행정예고 / 제개정고시 / 법령',
        'mfds.press':'보도자료','mfds.notices':'공지/공고',
        'industry.policy':'정책','industry.market':'시장',
        'industry.global':'글로벌','industry.rnd':'연구/개발',
        'industry.unclassified':'미분류 · 담당자 검토 필요'}


def txt(x):return escape(str(x or ''))

def effective(row,key):
    if key=='title':return row.get('title_override') if row.get('title_override') is not None else row['title']
    if key=='summary':
        return (row.get('summary_override') if row.get('summary_override') is not None else
                row.get('ai_summary') if row.get('ai_summary') is not None else row.get('summary_source',''))
    if key=='section':return row.get('section_override') or row.get('ai_section') or row.get('rule_section') or row['section']
    return row.get(key)

def link(x):
    from urllib.parse import urlsplit
    url=x['url']
    if urlsplit(url).scheme not in ('http','https'):return txt(effective(x,'title'))
    return f'<a style="color:#1c3854;text-decoration:underline" href="{escape(url,quote=True)}">{txt(effective(x,"title"))}</a>'

def _display_identity(row):
    """Identifies repeated *display entries*, not records to delete from SQLite.

    MFDS board ID + seq is reliable across tracking/search/page URL parameters.
    For other links, use exact original headline/date *within the same source*
    only; do not merge distinct approval events or different news providers.
    """
    url = urlsplit(row.get('url') or '')
    if row.get('source_group') == 'mfds' and url.hostname == 'www.mfds.go.kr':
        board = re.search(r'/brd/m_(\d+)/view\.do$', url.path)
        seq = parse_qs(url.query).get('seq', [None])[0]
        if board and seq:
            return ('mfds-board-record', board.group(1), seq)
    title = re.sub(r'\s+', ' ', row.get('title') or '').strip().casefold()
    day = row.get('published_at')
    if title and day:
        return ('exact-headline-day', row.get('source_key'), day, title)
    return ('record', row['id'])


def unique_for_display(items):
    """Suppress duplicate presentation only. Never change source rows or decisions."""
    seen = set()
    for item in items:
        key = _display_identity(item)
        if key in seen:
            continue
        seen.add(key)
        yield item


def list_html(items,group):
    res=[]
    for x in unique_for_display(items):
        label=txt(x.get('published_at') or '날짜 미확인') if group=='mfds' else txt(x['source_key'])
        res.append('<span style="display:block;padding:3px 0;line-height:1.7;font-size:13px" data-record-id="'+txt(x['id'])+'">'
                   +label+'　'+link(x)+'</span>')
    return ''.join(res) or '<span style="color:#8a5962;font-size:12px">확인된 수록 자료 없음 (수집 완료 여부 별도 확인)</span>'

def group_html(rows,group):
    parts=[]
    keys=[x for x in GROUPS if x.startswith(group+'.') and x != 'industry.unclassified']
    if group == 'industry':
        if any(x['include_detail'] and effective(x,'section') == 'industry.unclassified' for x in rows):
            keys.append('industry.unclassified')
    for key in keys:
        items=[x for x in rows if x['include_detail'] and effective(x,'section')==key]
        parts.append('<span style="display:block;margin:15px 0 7px;color:#2980b9;font-size:16px;font-weight:bold">'+txt(GROUPS[key])+'</span>')
        parts.append(list_html(items,group))
    if group == 'industry':
        candidates = [x for x in rows if x['source_group'] == 'industry']
        selected = [x for x in candidates if x['include_detail']]
        if candidates and not selected:
            parts.insert(0, '<p style="font-size:12px;color:#986b43">언론기사 후보 '+str(len(candidates))+'건이 있지만 상세 수록으로 선택되지 않았어. 편집 화면에서 수록 여부와 섹션을 확인해.</p>')
        elif not candidates:
            parts.insert(0, '<p style="font-size:12px;color:#986b43">이 회차에 등록된 언론기사 후보가 없어. 수집 상태를 확인해 (전체 0건 의미 아님).</p>')
    return ''.join(parts)

def approval_table(items,kind):
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
            aliases={'승인일':['승인일자','허가일','허가일자'],'임상시험제목':['임상시험 제목'],
                     '임상시험 단계':['임상시험단계','단계'], '제품명':['품목명','제품명칭']}
            value=raw.get(f) or next((raw.get(x) for x in aliases.get(f,[]) if raw.get(x)),None)
            if not value and f in ('임상시험제목','제품명'):value=r['title']
            if not value and f=='승인일':value=r.get('published_at')
            vals.append('<td style="padding:6px;vertical-align:top">'+txt(value or '—')+'</td>')
        parts.append('<tr>'+''.join(vals)+'</tr>')
    parts.append('</tbody></table>')
    parts.append('<p style="font-size:11px;color:#986b43">담당자 제공 CSV 기준 · 공식 원본 건수·데이터 정확성은 미검증</p>')
    return ''.join(parts)


def top_table(items):
    items=list(unique_for_display(items))
    if not items:return '<p style="padding:16px;color:#8a5962;font-size:13px">주요 뉴스 선정 대기</p>'
    result=['<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="border-collapse:collapse">']
    for i in range(0,len(items),2):
        result.append('<tr>')
        for x in items[i:i+2]:
            summary=txt(effective(x,'summary'))
            result.append('<td width="50%" valign="top" style="padding:5px">'
                          '<div style="border:2px solid #d3d3d3;padding:10px;font:13px/1.75 Malgun Gothic,Arial,sans-serif">'
                          +link(x)+ ('<p style="margin:7px 0 0;color:#343b45;font-size:12px">'+summary+'</p>' if summary else '')+'</div></td>')
        if i+1>=len(items):result.append('<td width="50%"></td>')
        result.append('</tr>')
    result.append('</table>')
    return ''.join(result)

def render(con,edition_id,template_path):
    edition=get_edition(con,edition_id)
    rows=edition_rows(con,edition_id)
    tops=sorted([r for r in rows if r['top_selected']],key=lambda r:(r['top_rank'] if r['top_rank'] is not None else 9999,r['id']))
    soup=BeautifulSoup(Path(template_path).read_text(encoding='utf-8'),'html.parser')
    first=soup.select_one('#i8voq4');second=soup.select_one('#icsna')
    if not first or not second:raise ValueError('Original 892 TOP layout markers not found')
    first.replace_with(BeautifulSoup(top_table(tops),'html.parser'))
    second.decompose()
    replacements={
       'company_news':list_html([r for r in rows if r['source_group']=='company' and r['include_detail']],'company'),
       'mfds_all':group_html(rows,'mfds'),
       'industry_all':group_html(rows,'industry')}
    for name,content in replacements.items():
        node=soup.select_one('[data-slot="'+name+'"]')
        if not node:raise ValueError('Required HTML slot missing: '+name)
        node.clear();node.append(BeautifulSoup(content,'html.parser'))
    title=soup.title
    if title:title.string='MEDiTIP 뉴스레터 - '+edition['title']+' [검토용]'
    banner=soup.find(string=lambda s:s and 'MEDITIP MVP 테스트' in s)
    if banner:banner.replace_with('MEDiTIP 뉴스레터 편집 초안 · '+edition['title']+' · 외부 발송 금지')
    clinical=soup.select_one('[data-image-slot="clinical_approvals"]')
    if clinical:
        clinic=[r for r in rows if r['source_group']=='clinical' and r['include_detail']]
        treatment=[r for r in rows if r['source_group']=='treatment' and r['include_detail']]
        if clinic or treatment:
            fragment=approval_table(clinic,'clinical')
            if treatment:
                fragment+='<p style="color:#2980b9;font-weight:bold">치료목적 사용승인</p>'+approval_table(treatment,'treatment')
            clinical.replace_with(BeautifulSoup(fragment,'html.parser'))
        else:clinical.string='임상시험 승인현황: 데이터 수집 연동 전 / 자동 작성되지 않음'
    drugs=[r for r in rows if r['source_group']=='drug' and r['include_detail']]
    if drugs:
        head=soup.find(string=lambda s:s and '주간 허가현황' in s and '의약품' in s)
        if head:
            anchor=head.find_parent('p') or head.parent
            anchor.insert_after(BeautifulSoup(approval_table(drugs,'drug'),'html.parser'))
    # Original 892 issue date/number is historic; it must not imply a new issued newsletter.
    for t in list(soup.find_all(string=True)):
        val=str(t)
        if '892호' in val and '발간수기' in val:
            t.replace_with('MEDiTIP 뉴스레터 편집 초안 ('+edition['period_start']+' ~ '+edition['period_end']+')')
        elif '11월' in val and '둘째 주' in val:
            if 'Meditip 주요' in val:
                t.replace_with('이번 호 Meditip 주요 소식')
            elif '산업' in val and '업데이트' in val:
                t.replace_with('제약 산업 및 제도 업데이트 ('+edition['period_start']+' ~ '+edition['period_end']+')')
        elif 'Copyright2015' in val:
            t.replace_with('MEDiTIP · 편집용 템플릿 / 법인 정보 확인 필요')
    for a in soup.find_all('a',href=True):
        if a.get('href','').strip()=='#':
            a.replace_with(BeautifulSoup('<span style="color:#607588">'+txt(a.get_text(' ',strip=True))+' (발송 시스템에서 설정)</span>','html.parser'))
    html=str(soup)
    if '{{' in html and '}}' in html:raise ValueError('Unresolved template slots remain')
    return html
