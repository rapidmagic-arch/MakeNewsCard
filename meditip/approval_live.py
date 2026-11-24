"""Read-only official public approval tables; no login, no hidden endpoints."""
import hashlib
import json
import re
from collections import Counter
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
import requests
from .collect import get, norm_date
from .db import save_item
from .source_links import approval_search_url

DOMAIN='nedrug.mfds.go.kr'
ROOT='https://'+DOMAIN
SPECS={
    'clinical':('/searchClinic', ('approvalDtStart','approvalDtEnd'), {'searchYn':'true','searchType':'ST3'},
                ('순번','진행현황','의뢰자','제품명','임상시험 제목','임상시험 단계','개발지역','실시기관','승인일'), '임상시험 제목','승인일','clinical.approval'),
    'treatment':('/pbp/CCBBQ01/getList', ('approvalDtStart','approvalDtEnd'), {},
                 ('순번','구분','신청인','승인일자','제품명','성분명','대상질환명'),'제품명','승인일자','clinical.treatment'),
    'drug':('/pbp/CCBAE01/getItemPermitIntro', ('sPermitDateStart','sPermitDateEnd'), {'sDateGb':'date'},
            ('순번','제품명','업체명','허가일자','취소/취하일자','전문/일반'),'제품명','허가일자','drug.approvals'),
}
LABELS={'clinical':'임상시험 승인','treatment':'치료목적 사용승인','drug':'의약품 허가'}
MAX_PAGES=100

def approval_url(kind,start,end,page=1):
    if kind not in SPECS:raise ValueError('Unknown approval category')
    return approval_search_url(kind,start,end,page=page)

def clean(node):
    return ' '.join(node.get_text(' ',strip=True).split())

def parse_approval_page(content,kind,start,end):
    path,dates,params,headers,title_field,date_field,section=SPECS[kind]
    soup=BeautifulSoup(content,'html.parser')
    form=soup.select_one('#searchForm')
    if form is None:raise ValueError('공식 조회 폼을 찾지 못했습니다.')
    for key,value in zip(dates,(start,end)):
        field=form.find('input',attrs={'name':key})
        if field is None or norm_date(field.get('value',''))!=value:
            raise ValueError('공식 사이트가 요청한 날짜 조건을 반환하지 않았습니다.')
    totals={int(x.replace(',','')) for x in re.findall(r'총\s*([\d,]+)\s*건',clean(soup))}
    if len(totals)!=1:raise ValueError('공식 조회 총 건수를 검증할 수 없습니다.')
    total=totals.pop()
    table=None
    for candidate in soup.select('table'):
        head=candidate.select_one('thead')
        if head is None:continue
        fields=tuple(clean(x) for x in head.select('th'))
        if fields==headers:
            if table is not None:raise ValueError('조회 표가 중복되었습니다.')
            table=candidate
    if table is None:raise ValueError('공식 조회 표의 열 구조가 변경되었습니다.')
    records=[]
    for tr in table.select('tbody tr'):
        cells=tr.find_all('td',recursive=False)
        if not cells:continue
        if len(cells)==1 and total==0 and cells[0].get('colspan'):continue
        if len(cells)!=len(headers):raise ValueError('공식 조회 표의 행 구조가 변경되었습니다.')
        for node in tr.select('.s-th,.th-title'):node.decompose()
        raw=dict(zip(headers,(clean(c) for c in cells)))
        try:number=int(raw.pop('순번').replace(',',''))
        except ValueError:raise ValueError('공식 조회 순번이 올바르지 않습니다.')
        approved=norm_date(raw.get(date_field))
        cancel=norm_date(raw.get('취소/취하일자'))
        if not approved or not raw.get(title_field):raise ValueError('승인 날짜 또는 제목 누락')
        within=start<=approved<=end
        if not within and not (kind=='drug' and cancel and start<=cancel<=end):
            raise ValueError('요청 기간 외 자료가 반환되었습니다.')
        href=''
        for anchor in cells[headers.index(title_field)].select('a[href]'):
            link=urljoin(ROOT,anchor['href'])
            if urlsplit(link).scheme=='https' and urlsplit(link).hostname==DOMAIN:
                href=link;break
        query=parse_qs(urlsplit(href).query)
        if kind=='clinical':
            stable=':'.join(query.get(k,[''])[0] for k in ('clinicExamSeq','clinicExamNo','receiptNo'))
            if not stable.strip(':'):raise ValueError('임상시험 원본 식별자 누락')
        elif kind=='drug':
            stable=query.get('itemSeq',[''])[0]
            if not stable:raise ValueError('의약품 원본 식별자 누락')
        else:
            # No public event number: retain identical-row multiplicity and expose derived identity.
            stable=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        records.append(dict(number=number,raw=raw,approved=approved,within=within,stable=stable,
                            href=href,title=raw[title_field],section=section))
    if (total==0 and records) or (total>0 and not records):raise ValueError('조회 건수와 행 불일치')
    return total,records

def fetch_approval(kind,start,end,session=None):
    if kind not in SPECS:raise ValueError('Unknown approval category')
    own=session is None
    session=session or requests.Session()
    all_rows=[];expected=None
    try:
        for page in range(1,MAX_PAGES+1):
            url=approval_url(kind,start,end,page)
            response=get(session,url,DOMAIN)
            total,rows=parse_approval_page(response.content,kind,start,end)
            if expected is None:expected=total
            if total!=expected:raise ValueError('페이지 사이 공식 조회 건수가 바뀌었습니다.')
            if [x['number'] for x in rows]!=list(range(len(all_rows)+1,len(all_rows)+len(rows)+1)):
                raise ValueError('페이지 순번이 연속되지 않습니다.')
            all_rows.extend(rows)
            if len(all_rows)>total:raise ValueError('공식 조회 건수 초과')
            if len(all_rows)==total:break
        else:raise ValueError('페이지 제한에 도달하여 전체 수집을 완료하지 못했습니다.')
    finally:
        if own:session.close()
    return {'total':expected,'pages':page,'rows':all_rows,'query_url':approval_url(kind,start,end)}

def ensure_single_approval_mode(con,kind,edition,mode):
    other='official_csv_'+kind if mode=='live' else 'official_live_'+kind
    if con.execute('SELECT 1 FROM items WHERE source_key=? AND published_at BETWEEN ? AND ? LIMIT 1',
                   (other,edition['period_start'],edition['period_end'])).fetchone():
        raise ValueError('같은 기간·자료 유형에 다른 방식으로 등록된 자료가 있습니다. 중복 방지를 위해 자동 혼합하지 않습니다.')

def save_live_approval(con,kind,edition,result):
    ensure_single_approval_mode(con,kind,edition,'live')
    stats={'new':0,'changed':0,'unchanged':0};occurrence=Counter()
    accepted=0;cancelled=0
    for row in result['rows']:
        if not row['within']:
            cancelled+=1;continue
        identity=row['stable']+':'+row['approved']
        occurrence[identity]+=1
        if kind!='treatment' and occurrence[identity]>1:raise ValueError('공식 원본 식별자가 중복되었습니다.')
        event=identity+(':'+str(occurrence[identity]) if kind=='treatment' else '')
        path=SPECS[kind][0]
        save_item(con,dict(source_key='official_live_'+kind,source_group=kind,section=row['section'],
             source_id=event,url=ROOT+path,title=row['title'],published_at=row['approved'],
             verification='official_public_list',relevance='relevant',mandatory=True,
             original_metadata={'approval_row':row['raw'],'approval_kind':kind,
                                'source_url':row['href'] or result['query_url'],
                                'identity_method':'public_fields_and_occurrence' if kind=='treatment' else 'public_event_id'}),stats=stats)
        accepted+=1
    return {'records':accepted,'official_total':result['total'],'cancelled_only':cancelled,
            'pages':result['pages'],'save_counts':stats,'query_url':result['query_url']}
