"""Local operator supplied company news. No automatic source verification."""
from datetime import date
from urllib.parse import urlsplit
from .db import save_item, edition_rows, canonical_url
from .workflow import require_draft
from .edition import prepare

def register_company(con,edition_id,payload,config=None):
    ed=require_draft(con,edition_id)
    def field(key,limit,required=True):
        value=payload.get(key,'')
        if not isinstance(value,str) or len(value.strip())>limit or (required and not value.strip()):
            raise ValueError('Invalid company news '+key)
        return value.strip()
    title=field('title',500)
    url=canonical_url(field('url',2000))
    parsed=urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter a public HTTP(S) article URL')
    publisher=field('publisher',100)
    published=field('published_at',10)
    if date.fromisoformat(published).isoformat()!=published or not ed['period_start']<=published<=ed['period_end']:
        raise ValueError('기사 날짜는 현재 수집 기간에 포함되어야 합니다.')
    summary=field('summary',2000,False)
    previous=next((x for x in edition_rows(con,edition_id) if x['source_group']=='company' and x['url']==url),None)
    if previous:
        raise ValueError('현재 회차에 이미 등록된 회사 소식입니다. 상세 편집을 이용하세요.')
    iid=save_item(con,{'source_key':'company_manual','source_group':'company','section':'company.news',
        'url':url,'title':title,'published_at':published,'summary_source':summary,
        'verification':'operator_provided','original_metadata':{'publisher':publisher}})
    prepare(con,edition_id,config)
    return iid

def company_rows(rows):
    return sorted((r for r in rows if r['source_group']=='company'),
                  key=lambda r:(r.get('company_rank') if r.get('company_rank') is not None else 999999,r['id']))

def set_company_order(con,edition_id,ids):
    require_draft(con,edition_id)
    expected={r['id'] for r in company_rows(edition_rows(con,edition_id))}
    if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids) or len(ids)!=len(expected) or set(ids)!=expected:
        raise ValueError('회사 소식 순서가 현재 회차와 일치하지 않습니다.')
    for rank,iid in enumerate(ids,1):
        con.execute('UPDATE decisions SET company_rank=? WHERE edition_id=? AND item_id=?',(rank,edition_id,iid))
    con.commit()
