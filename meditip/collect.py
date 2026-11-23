"""Small metadata-first collectors. Browser/API/Excel remain independent adapters.
No login bypass, no hidden endpoints and no completeness claims without audit.
"""
import email.utils
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup
from .db import save_item, log_run

UA='MeditipNewsletterMVP/0.1 (public metadata; manual newsletter review)'
DATE_RE=re.compile(r'(?<!\d)((?:20\d\d)[.\-/](?:0?[1-9]|1[0-2])[.\-/](?:0?[1-9]|[12]\d|3[01]))(?!\d)')
ARTICLE_RE=re.compile(r'(?:/brd/m_\d+/view\.do\?[^#]*seq=\d+|articleView\.html\?idxno=\d+|NewsView\.html\?ID=\d+|mode=view[^#]*nid=\d+|/user/news/\d+)',re.I)


def norm_date(text):
    if not text:return None
    m=DATE_RE.search(text)
    if m:
        try: return datetime.strptime(re.sub(r'[./]','-',m.group(1)),'%Y-%m-%d').date().isoformat()
        except ValueError:return None
    try:
        dt=email.utils.parsedate_to_datetime(text)
        return dt.date().isoformat()
    except (ValueError,TypeError,IndexError):return None


def get(session,url,allowed_domain):
    p=urlparse(url)
    if p.scheme!='https' or p.hostname!=allowed_domain:raise ValueError('Unapproved source domain')
    res=session.get(url,timeout=(7,18),headers={'User-Agent':UA},allow_redirects=True)
    res.raise_for_status()
    if urlparse(res.url).hostname!=allowed_domain: raise ValueError('Redirect crossed source domain')
    if len(res.content)>8_000_000:raise ValueError('Response too large')
    return res


def parse_feed(content,base,source_key,section):
    root=ET.fromstring(content)
    out=[]
    # RSS2 and Atom supported; XML is not an authenticated completeness signal
    is_atom=root.tag.endswith('feed')
    nodes=root.findall('{http://www.w3.org/2005/Atom}entry') if is_atom else root.findall('.//item')
    for el in nodes:
        def child(name):
            for x in el:
                if x.tag.rsplit('}',1)[-1]==name:return (x.text or '').strip()
            return ''
        title=re.sub(r'\s+',' ',BeautifulSoup(child('title'),'html.parser').get_text(' ',strip=True))
        url=''
        if is_atom:
            for link in el:
                if link.tag.rsplit('}',1)[-1]=='link' and link.get('href') and link.get('rel','alternate')=='alternate':url=link.get('href');break
        else:url=child('link')
        url=urljoin(base,url)
        if not title or urlparse(url).scheme not in ('https','http'):continue
        if urlparse(url).hostname!=urlparse(base).hostname:continue
        out.append({'source_key':source_key,'source_group':'mfds','section':section,
                    'url':url,'source_id':child('guid') or None,'title':title,
                    'published_at':norm_date(child('pubDate') or child('published') or child('updated')),
                    'verification':'metadata_only', 'mandatory':False,
                    'relevance':'review_needed','original_metadata':{'discovery_method':'rss','rss_url':base}})
    return out


def parse_public_list(content,base,source_key,source_group,section):
    soup=BeautifulSoup(content,'html.parser');out={}
    for a in soup.find_all('a',href=True):
        href=urljoin(base,a['href']);p=urlparse(href)
        if p.hostname!=urlparse(base).hostname or not ARTICLE_RE.search(href):continue
        title=' '.join(a.get_text(' ',strip=True).split())
        if len(title)<8: continue
        surrounding=a.find_parent('tr') or a.find_parent('li') or a.find_parent('article') or a.parent
        date=norm_date(surrounding.get_text(' ',strip=True)[:500])
        query=parse_qs(p.query)
        sid=(query.get('seq') or query.get('idxno') or query.get('ID') or query.get('nid') or [None])[0]
        out[href]={ 'source_key':source_key,'source_group':source_group,'section':section,
                   'source_id':sid,'url':href,'title':title,'published_at':date,
                   'verification':'metadata_only','relevance':'review_needed',
                   'mandatory':False,'original_metadata':{'discovery_method':'public_list','list_url':base}}
    return list(out.values())


def source_specs(config):
    for board in config['sources']['mfds']['boards']:
        yield {**board,'group':'mfds','method':'mfds_board'}
    for media in config['sources']['industry']['media']:
        yield {**media,'group':'industry','method':'public_list','html_section':'industry.unclassified'}
    # Approval APIs / Excel and BD files are explicitly separate connectors, not page scraping


def collect_source(con,spec,start,end,mode='board',max_pages=2,delay=1.1,session=None):
    session=session or requests.Session();key=spec['key'];grp=spec['group']
    domain=urlparse(spec['url']).hostname
    records=[];pages=0;issues=[];status='partial'
    try:
        if mode=='rss':
            if grp!='mfds' or not spec.get('rss_id'):raise ValueError('RSS mapping not configured for this source')
            url=f'https://www.mfds.go.kr/www/rss/brd.do?brdId={spec["rss_id"]}'
            r=get(session,url,domain);pages+=1
            for x in parse_feed(r.content,url,key,spec['html_section']):
                if x['published_at'] is None or start<=x['published_at']<=end:records.append(x)
            # RSS does not prove the board is complete.
            issues.append('RSS discovery only; board comparison required')
        else:
            if not 1<=max_pages<=50:raise ValueError('max_pages must be 1..50')
            for page in range(1,max_pages+1):
                url=spec['url']; sep='&' if '?' in url else '?'
                if grp=='mfds':url+=f'{sep}page={page}'
                elif page>1:break # media pagination shape not confirmed; first page metadata only
                r=get(session,url,domain);pages+=1
                rows=parse_public_list(r.content,r.url,key,grp,spec.get('html_section','industry.unclassified'))
                if not rows:
                    issues.append(f'No article links parsed on page {page}; selector needs validation')
                    break
                relevant=[x for x in rows if x['published_at'] is None or start<=x['published_at']<=end]
                records.extend(relevant)
                if len([x for x in rows if x['published_at'] is None])>0:
                    issues.append(f'Undated list entries on page {page}; page coverage unknown')
                if page<max_pages:time.sleep(delay)
            issues.append('Page coverage unverified; cannot mark complete automatically')
        for x in records:save_item(con,x)
        con.commit()
    except Exception as exc:
        issues.append(type(exc).__name__+': '+str(exc)[:260]);status='failed' if pages==0 else 'partial'
    log_run(con,key,start,end,status,pages,len(records),{'mode':mode,'issues':issues})
    return {'source':key,'status':status,'pages':pages,'records':len(records),'issues':issues}


def import_snapshot(con,payload,source='historical_sample'):
    """Imports prior 892-derived 7-record sample as unverified historical fixture."""
    data=payload.get('records') if isinstance(payload,dict) else payload
    if not isinstance(data,list):raise ValueError('Expected records array')
    n=0
    for r in data:
        url=r.get('original_url') or r.get('url')
        if not url or not r.get('title'):continue
        cat=r.get('category') or 'unclassified'
        group='mfds' if cat.startswith('mfds.') else ('industry' if cat.startswith('industry.') else 'company')
        # preserve original IDs and summaries, but not claim that the source was rechecked
        item={'id':r.get('id'), 'source_key':source,'source_group':group,'section':cat,
              'url':url,'title':r['title'],'published_at':r.get('published_at'),
              'summary_source':r.get('summary') or '',
              'verification':'historical_fixture_not_rechecked',
              'relevance':'review_needed','mandatory':group=='mfds',
              'original_metadata':{'fixture_source':source,'original_verification':r.get('verification')}}
        save_item(con,item);n+=1
    con.commit()
    log_run(con,source,None,None,'partial',0,n,{'import_type':'historical_fixture','not_a_live_collection':True})
    return n


def import_approval_csv(con,path,kind='clinical'):
    """User-provided export fallback. CSV metadata is NOT an official source verification.
    Supports clinical/treatment/drug. No original event ID is invented.
    """
    import csv,hashlib
    from pathlib import Path
    if kind not in ('clinical','treatment','drug'):raise ValueError('Unknown approval category')
    content=Path(path).read_bytes()
    decoded=None
    for codec in ('utf-8-sig','cp949'):
        try:decoded=content.decode(codec);break
        except UnicodeDecodeError:pass
    if decoded is None:raise ValueError('CSV encoding not supported')
    rows=csv.DictReader(decoded.splitlines())
    if not rows.fieldnames:raise ValueError('Empty CSV')
    official={'clinical':'https://nedrug.mfds.go.kr/searchClinic',
              'treatment':'https://nedrug.mfds.go.kr/pbp/CCBBQ01',
              'drug':'https://nedrug.mfds.go.kr/pbp/CCBAE01'}
    n=0;skipped=[]
    for line,src in enumerate(rows,2):
        src={str(k or '').strip():str(v or '').strip() for k,v in src.items()}
        def field(*names):return next((src[x] for x in names if src.get(x)),'')
        approved=norm_date(field('승인일','승인일자','허가일','허가일자'))
        title=(field('임상시험제목','임상시험 제목','제목') if kind=='clinical' else
               field('제품명','품목명','제품명칭'))
        if not approved or not title:
            skipped.append({'line':line,'reason':'required approval date or title missing'});continue
        event=field('승인번호','접수번호','허가번호') or hashlib.sha256(json.dumps(src,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
        source_key=f'official_csv_{kind}'
        item={'source_key':source_key,'source_group':kind,
              'section':{'clinical':'clinical.approval','treatment':'clinical.treatment','drug':'drug.approvals'}[kind],
              'source_id':event+':'+approved+':'+field('승인유형','구분','변경구분'),
              'url':official[kind],'title':title,
              'published_at':approved,'verification':'provided_export_not_source_verified',
              'relevance':'relevant','mandatory':True,
              'original_metadata':{'csv_row':src,'csv_line':line,'approval_kind':kind}}
        save_item(con,item);n+=1
    con.commit()
    log_run(con,f'csv_{kind}',None,None,'partial',0,n,
            {'method':'user_provided_csv','skipped':skipped,'not_official_live_collection':True})
    return {'imported':n,'skipped':skipped}
