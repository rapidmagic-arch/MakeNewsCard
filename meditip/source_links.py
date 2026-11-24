"""Presentation-only source links, distinct from the stored record identity URL."""
import json
import re
from datetime import date
from urllib.parse import urlsplit, parse_qs, urlencode

ROOT='https://nedrug.mfds.go.kr'
SEARCH={
    'clinical':('/searchClinic','approvalDtStart','approvalDtEnd',{'searchYn':'true','searchType':'ST3'}),
    'treatment':('/pbp/CCBBQ01/getList','approvalDtStart','approvalDtEnd',{}),
    'drug':('/pbp/CCBAE01/getItemPermitIntro','sPermitDateStart','sPermitDateEnd',{'sDateGb':'date'}),
}
LANDING={'clinical':'/searchClinic','treatment':'/pbp/CCBBQ01','drug':'/pbp/CCBAE01'}

def safe_http(url):
    if not isinstance(url,str) or not url or any(ord(c)<33 or c=='\\' for c in url):
        return ''
    try:
        p=urlsplit(url)
        return url if p.scheme in ('https','http') and p.hostname and not p.username and not p.password else ''
    except ValueError:
        return ''

def valid_date(value):
    try:return isinstance(value,str) and date.fromisoformat(value).isoformat()==value
    except ValueError:return False

def approval_search_url(kind,start,end,filters=None,page=1):
    path,first,last,defaults=SEARCH[kind]
    if not valid_date(start) or not valid_date(end) or start>end:
        return ROOT+LANDING[kind]
    return ROOT+path+'?'+urlencode({**defaults,first:start,last:end,'page':page,**(filters or {})})

def _official_detail(url,kind):
    if not safe_http(url):return ''
    p=urlsplit(url)
    if p.scheme!='https' or p.netloc!='nedrug.mfds.go.kr':return ''
    q=parse_qs(p.query)
    def numeric(key):
        values=q.get(key,[])
        return len(values)==1 and bool(re.fullmatch(r'[0-9]+',values[0]))
    if kind=='clinical' and p.path=='/pbp/CCBBC01/nexacroPageOpen' and all(numeric(k) for k in ('clinicExamSeq','clinicExamNo','receiptNo')):
        return url
    if kind=='drug' and p.path=='/pbp/CCBBB01/getItemDetail' and numeric('itemSeq'):
        return url
    return ''

def resolve_source_link(row):
    """Return (URL, kind): detail, search, or source. No live network call."""
    row=dict(row)
    original=safe_http(row.get('url'))
    key=row.get('source_key','')
    kind=row.get('source_group')
    if kind not in SEARCH or key not in ('official_live_'+kind,'official_csv_'+kind):
        return original,'detail'
    try:meta=json.loads(row.get('original_metadata') or '{}')
    except (TypeError,ValueError):meta={}
    if not isinstance(meta,dict):meta={}
    # Trust only actual captured, allowlisted detail URLs; CSV fields are not verified IDs.
    if key.startswith('official_live_'):
        detail=_official_detail(meta.get('source_url'),kind) or _official_detail(original,kind)
        if detail:return detail,'detail'
    raw=meta.get('approval_row') or meta.get('csv_row') or {}
    if not isinstance(raw,dict):raw={}
    def field(*names):
        for name in names:
            value=raw.get(name)
            if isinstance(value,str) and value.strip() and value.strip() not in ('-','—'):
                return value.strip()
        return ''
    approved=row.get('published_at')
    if not valid_date(approved):return ROOT+LANDING[kind],'source'
    product=field('제품명','품목명','제품명칭')
    if kind=='clinical':
        title=field('임상시험제목','임상시험 제목','제목') or row.get('title','')
        filters={'searchType':'ST2','searchKeyword':product} if product else {'searchType':'ST3','searchKeyword':title}
    elif kind=='treatment':
        filters={'prductName':product or row.get('title',''),'applyEntpName':field('신청인')}
    else:
        filters={'sItemName':product or row.get('title',''),'sEntpName':field('업체명')}
    filters={k:v for k,v in filters.items() if isinstance(v,str) and v.strip()}
    return approval_search_url(kind,approved,approved,filters),'search'
