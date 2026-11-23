"""Small metadata-first collectors. Browser/API/Excel remain independent adapters.
No login bypass, no hidden endpoints and no completeness claims without audit.
"""
import email.utils
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
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


def mfds_post_key(url):
    """Stable ID for one MFDS board posting, regardless of page/search parameters."""
    p = urlsplit(url)
    m = re.fullmatch(r'/brd/m_(\d+)/view\.do', p.path)
    seq = parse_qs(p.query).get('seq', [None])[0]
    if p.hostname not in ('www.mfds.go.kr', 'mfds.go.kr') or not m or not seq or not seq.isdecimal():
        return None
    return (m.group(1), seq)


def mfds_canonical_link(url):
    """Strip page/search parameters only when a board/seq identity is verified."""
    key = mfds_post_key(url)
    if key is None:
        return url
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode({'seq': key[1]}), ''))


def mfds_list_url(base, page, start, end):
    """Send the official site's documented search parameter names, verify results client-side too."""
    p = urlsplit(base)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.update(page=str(page), srchFr=start, srchTo=end)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ''))


def collect_source(con,spec,start,end,mode='board',max_pages=2,delay=1.1,session=None,edition_id=None):
    """Collect metadata; never label a limited or unverified scan as complete."""
    session=session or requests.Session()
    key=spec['key'];grp=spec['group']
    domain=urlparse(spec['url']).hostname
    records=[];pages=0;issues=[];status='partial'
    seen=set();duplicate_rows=0;undated=0
    audit={'mode':mode,'period':{'start':start,'end':end}}
    try:
        if mode=='rss':
            if grp!='mfds' or not spec.get('rss_id'):
                raise ValueError('RSS mapping not configured for this source')
            url=f'https://www.mfds.go.kr/www/rss/brd.do?brdId={spec["rss_id"]}'
            r=get(session,url,domain);pages+=1
            for item in parse_feed(r.content,url,key,spec['html_section']):
                if item['published_at'] is not None and not (start<=item['published_at']<=end):
                    continue
                if item['published_at'] is None:undated+=1
                if grp=='mfds':item['url']=mfds_canonical_link(item['url'])
                identity=mfds_post_key(item['url']) or ('url',item['url'])
                if identity in seen:
                    duplicate_rows+=1;continue
                seen.add(identity);records.append(item)
            issues.append('RSS discovery only; list-page coverage must be checked independently')
        else:
            if not 1<=max_pages<=50:raise ValueError('max_pages must be 1..50')
            for page in range(1,max_pages+1):
                url=(mfds_list_url(spec['url'],page,start,end) if grp=='mfds'
                     else spec['url'])
                if grp=='industry' and page>1:
                    break # pagination shape remains unverified
                r=get(session,url,domain);pages+=1
                rows=parse_public_list(r.content,r.url,key,grp,spec.get('html_section','industry.unclassified'))
                if not rows:
                    issues.append(f'No article links parsed on page {page}; selector needs validation')
                    break
                fresh=0
                for item in rows:
                    published=item['published_at']
                    if published is not None and not (start<=published<=end):continue
                    if published is None:undated+=1
                    if grp=='mfds':item['url']=mfds_canonical_link(item['url'])
                    identity=mfds_post_key(item['url']) if grp=='mfds' else None
                    identity=identity or ('url',item['url'])
                    if identity in seen:
                        duplicate_rows+=1;continue
                    seen.add(identity);records.append(item);fresh+=1
                if not fresh:
                    issues.append(f'No new in-range records on page {page}; check pagination/date filtering')
                    break
                if page<max_pages:time.sleep(delay)
            issues.append('Page coverage unverified; cannot mark complete automatically')
            # Compare only overlapping observed RSS/board IDs. RSS may be truncated.
            if grp=='mfds' and spec.get('rss_id'):
                rss_url=f'https://www.mfds.go.kr/www/rss/brd.do?brdId={spec["rss_id"]}'
                try:
                    feed=get(session,rss_url,domain)
                    rss_records=parse_feed(feed.content,rss_url,key,spec['html_section'])
                    rss_ids={x for row in rss_records
                             if row['published_at'] is not None and start<=row['published_at']<=end
                             if (x:=mfds_post_key(row['url'])) is not None}
                    board_ids={x for row in records if (x:=mfds_post_key(row['url'])) is not None}
                    missing=sorted(rss_ids-board_ids)
                    audit['rss_crosscheck']={'status':'compared','rss_identified':len(rss_ids),
                                             'board_identified':len(board_ids),
                                             'rss_not_on_board':[f'm_{b}:seq={seq}' for b,seq in missing[:25]],
                                             'rss_not_on_board_count':len(missing)}
                    if missing:issues.append(f'RSS has {len(missing)} dated IDs not found in scanned board pages')
                except Exception as exc:
                    audit['rss_crosscheck']={'status':'failed', 'error':type(exc).__name__}
                    issues.append('RSS comparison failed: '+type(exc).__name__)
            elif grp=='mfds':
                audit['rss_crosscheck']={'status':'not_configured'}
        if undated:issues.append(f'{undated} entries have no reliably parsed date; date coverage needs review')
    except Exception as exc:
        issues.append(type(exc).__name__+': '+str(exc)[:260]);status='failed' if pages==0 else 'partial'
    # Preserve usable earlier pages even if a subsequent page or cross-check fails.
    item_ids=[save_item(con,item) for item in records]
    con.commit()
    audit.update(issues=issues,duplicate_rows=duplicate_rows,undated=undated)
    log_run(con,key,start,end,status,pages,len(records),audit,edition_id=edition_id)
    return {'source':key,'status':status,'pages':pages,'records':len(records),'item_ids':item_ids,
            'duplicate_rows':duplicate_rows,'undated':undated,
            'rss_crosscheck':audit.get('rss_crosscheck'), 'issues':issues}


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
