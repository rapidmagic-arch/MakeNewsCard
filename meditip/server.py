"""Local editorial UI: collection jobs, SQLite decisions and HTML drafts.

Only configured sources can be collected.  Jobs run sequentially in one background
thread so the localhost editor can keep responding while network requests run.
"""
import json
import re
import secrets
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .collect import collect_source, source_specs
from .db import connect, edition_rows, ensure_edition, get_edition, log_run
from .edition import prepare, set_top_order, update_decision, bulk_industry, import_ai
from .render import render
from .workflow import require_draft, confirm, confirmed_html, confirm_details, week_label
from .ai_review import review_payload, analyze, ask, configured as ai_configured
from .review_groups import init_groups, list_groups, save_group, delete_group, with_groups


def _dates(start, end):
    if not all(isinstance(x, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', x) for x in (start, end)):
        raise ValueError('Dates must use YYYY-MM-DD')
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first or (last - first).days > 366:
        raise ValueError('Invalid collection period (maximum 367 calendar days)')
    return first, last


def serve(db_path, template_path, editor_path, edition_id, port=8765,
          sources_path=None, editorial_path=None):
    token = secrets.token_urlsafe(32)
    root = Path(editor_path).resolve().parent
    editor = Path(editor_path).read_text(encoding='utf8')
    editor_css = (root/'assets'/'editor.css').read_text(encoding='utf8')
    sources_path = Path(sources_path or root/'config'/'sources.yaml')
    editorial_path = Path(editorial_path or root/'config'/'editorial.yaml')
    configured = {s['key']: s for s in source_specs(yaml.safe_load(sources_path.read_text(encoding='utf8')))}
    # Recompute only machine proposals for existing edition items on upgrade.
    # prepare() deliberately does not replace human choices or manually edited text.
    with connect(db_path) as con:
        editorial_defaults=yaml.safe_load(editorial_path.read_text(encoding='utf8')) or {}
        init_groups(con,editorial_defaults.get('industry_section_keywords'))
        if get_edition(con,edition_id)['status']=='draft':
            prepare(con, edition_id, with_groups(con,editorial_defaults))
    template_path = str(template_path)
    active = {'edition': edition_id}
    lock = threading.Lock()
    job = {'state': 'idle', 'results': [], 'processed': 0, 'total': 0, 'current': None,
           'error': None, 'edition_id': edition_id}
    ai_job = {'state':'idle','processed':0,'total':0,'error':None,'edition_id':edition_id}

    def job_snapshot():
        with lock:
            return json.loads(json.dumps(job, ensure_ascii=False))

    def run_collection(keys, mode, start, end, max_pages, edition):
        try:
            collected_ids=[]
            for key in keys:
                spec = configured[key]
                with lock:
                    job['current'] = key
                try:
                    # A separate SQLite connection per job; no connection is shared across threads.
                    with connect(db_path) as con:
                        result = collect_source(con, spec, start, end, mode, max_pages, edition_id=edition)
                except Exception as exc:
                    result = {'source': key, 'status': 'failed', 'pages': 0, 'records': 0,
                              'issues': [type(exc).__name__ + ': ' + str(exc)[:200]]}
                    with connect(db_path) as con:
                        log_run(con, key, start, end, 'failed', 0, 0, {'mode': mode, 'issues': result['issues']}, edition_id=edition)
                # IDs are internal provenance, not browser progress logs.
                collected_ids.extend(result.pop('item_ids',[]))
                with lock:
                    job['results'].append(result)
                    job['processed'] += 1
            # Preserve existing manual editorial decisions; prepare updates only rule proposals.
            with connect(db_path) as con:
                rules = yaml.safe_load(editorial_path.read_text(encoding='utf8'))
                prepare(con, edition, with_groups(con,rules), extra_ids=collected_ids)
            with lock:
                job['state'] = 'finished'
        except Exception as exc:
            with lock:
                job['state'] = 'failed'
                job['error'] = type(exc).__name__ + ': ' + str(exc)[:200]
        finally:
            with lock:
                job['current'] = None
                job['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')

    def run_ai_review(payload, edition):
        try:
            proposal = analyze(payload)
            with connect(db_path) as con:
                if review_payload(con,edition,[x['id'] for x in payload['items']])['input_sha256'] != payload['input_sha256']:
                    raise ValueError('AI 분석 중 원본 후보가 바뀌었어. 다시 분석해.')
                import_ai(con, edition, proposal)
            with lock:
                ai_job.update(state='finished',processed=len(proposal['items']),
                              result_count=len(proposal['items']))
        except Exception as exc:
            with lock:
                ai_job.update(state='failed',error=f'{type(exc).__name__}: {str(exc)[:230]}')
        finally:
            with lock:
                ai_job['finished_at']=datetime.now(timezone.utc).isoformat(timespec='seconds')

    class Handler(BaseHTTPRequestHandler):
        def _respond(self, status, body, content_type='application/json; charset=utf-8', download=None):
            if isinstance(body, str):
                body = body.encode('utf8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'self'")
            if download:
                self.send_header('Content-Disposition', f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=200):
            self._respond(status, json.dumps(obj, ensure_ascii=False).encode('utf8'))

        def _local_host(self):
            return self.headers.get('Host', '') in (f'127.0.0.1:{port}', f'localhost:{port}')

        def do_GET(self):
            if not self._local_host():
                self._json({'error': 'Localhost only'}, 403)
                return
            p = urlsplit(self.path).path
            try:
                if p == '/':
                    self._respond(200, editor.replace('__LOCAL_TOKEN__', token), 'text/html; charset=utf-8')
                    return
                if p == '/assets/editor.css':
                    self._respond(200,editor_css,'text/css; charset=utf-8')
                    return
                if p == '/api/edition':
                    with connect(db_path) as con:
                        edition = get_edition(con, active['edition'])
                        items = edition_rows(con, active['edition'])
                        # Never mix historic global runs or other editions into current counters.
                        runs = [dict(r) for r in con.execute(
                            'SELECT * FROM runs WHERE edition_id=? ORDER BY id DESC LIMIT 30', (active['edition'],))]
                        total_runs = con.execute('SELECT COUNT(*) FROM runs WHERE edition_id=?', (active['edition'],)).fetchone()[0]
                        undated = sum(not item.get('published_at') for item in items)
                        out_of_period = sum(bool(item.get('published_at')) and
                           not edition['period_start'] <= item['published_at'] <= edition['period_end'] for item in items)
                        confirmation = confirm_details(con,active['edition'])
                    self._json({'edition': edition, 'items': items, 'runs': runs,
                                'confirmation':confirmation,
                                'week_label':week_label(edition['period_start'],edition['period_end']),
                                'run_total':total_runs,'undated_count':undated,
                                'out_of_period_count':out_of_period})
                    return
                if p == '/api/editions':
                    with connect(db_path) as con:
                        editions=[dict(row) for row in con.execute('SELECT id,title,period_start,period_end,status,issue_number,confirmed_at FROM editions ORDER BY created_at DESC,id DESC')]
                    self._json({'active':active['edition'],'editions':editions})
                    return
                if p == '/api/settings':
                    with connect(db_path) as con:
                        ed=get_edition(con,active['edition'])
                        groups=list_groups(con)
                    editorial=yaml.safe_load(editorial_path.read_text(encoding='utf8'))
                    self._json({'sources':[{'key':v['key'],'group':v['group'],'url':v['url']} for v in configured.values()],
                                'interest_terms':editorial.get('interest_terms',[]),
                                'industry_section_keywords':editorial.get('industry_section_keywords',{}),
                                'review_groups':groups,
                                'top_target':ed['top_target'],'ai_api_available':ai_configured(),
                                'config_files':['config/sources.yaml','config/editorial.yaml']})
                    return
                if p == '/api/review-groups':
                    with connect(db_path) as con:
                        self._json({'groups':list_groups(con)})
                    return
                if p == '/api/ai/job':
                    with lock:
                        self._json(json.loads(json.dumps(ai_job,ensure_ascii=False)))
                    return
                if p == '/api/sources':
                    self._json({'sources': [{
                        'key': x['key'], 'group': x['group'], 'method': x['method'],
                        'url': x['url'], 'rss_available': bool(x.get('rss_id')),
                        'rights_check_required': bool(x.get('rights_check_required'))
                    } for x in configured.values()]})
                    return
                if p == '/api/collection':
                    self._json(job_snapshot())
                    return
                if p in ('/export/html','/preview/html'):
                    with connect(db_path) as con:
                        html = confirmed_html(con,active['edition'])
                        if html is None:
                            html = render(con,active['edition'],template_path,preview=(p == '/preview/html'))
                    self._respond(200, html, 'text/html; charset=utf-8',
                                  download=f'newsletter_{active["edition"]}.html' if p == '/export/html' else None)
                    return
                if p == '/export/snapshot':
                    with connect(db_path) as con:
                        row=con.execute('SELECT raw_json FROM edition_confirmations WHERE edition_id=?',(active['edition'],)).fetchone()
                    if not row:
                        self._json({'error':'확정본이 없어.'},404)
                    else:
                        self._respond(200,row['raw_json'],'application/json; charset=utf-8',
                                      download=f'confirmed_{active["edition"]}.json')
                    return
                if p == '/export/ai':
                    with connect(db_path) as con:
                        payload=review_payload(con,active['edition'])
                    self._respond(200,json.dumps(payload,ensure_ascii=False,indent=2),
                                  'application/json; charset=utf-8',download=f'ai_candidates_{active["edition"]}.json')
                    return
                if p == '/export/json':
                    with connect(db_path) as con:
                        obj = {'edition': get_edition(con, active['edition']),
                               'items': edition_rows(con, active['edition'])}
                    self._respond(200, json.dumps(obj, ensure_ascii=False, indent=2),
                                  'application/json; charset=utf-8',
                                  download=f'newsletter_{active["edition"]}.json')
                    return
                self._json({'error': 'Not found'}, 404)
            except (ValueError, KeyError, TypeError) as exc:
                self._json({'error': str(exc)}, 400)

        def do_POST(self):
            if not self._local_host():
                self._json({'error': 'Localhost only'}, 403)
                return
            if (self.headers.get('X-Local-Token') != token or
                    self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json'):
                self._json({'error': 'Unauthorized local edit'}, 403)
                return
            origin = self.headers.get('Origin', '')
            if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                self._json({'error': 'Unexpected Origin'}, 403)
                return
            try:
                n = int(self.headers.get('Content-Length', '0') or 0)
                p = urlsplit(self.path).path
                max_payload = 1_000_000 if p == '/api/ai/import' else 100_000
                if not 0 < n <= max_payload:
                    raise ValueError('Bad payload size')
                obj = json.loads(self.rfile.read(n))
                if not isinstance(obj, dict):
                    raise ValueError('JSON object required')
                p = urlsplit(self.path).path
                if p == '/api/collect':
                    keys = obj.get('sources')
                    mode = obj.get('method', 'board')
                    start, end = obj.get('start'), obj.get('end')
                    _dates(start, end)
                    if not isinstance(keys, list) or not keys or len(keys) > len(configured):
                        raise ValueError('Select one or more configured sources')
                    if any(not isinstance(k, str) or k not in configured for k in keys) or len(keys) != len(set(keys)):
                        raise ValueError('Unknown or duplicate source')
                    if mode not in ('rss', 'board'):
                        raise ValueError('Unknown collection method')
                    if mode == 'rss' and any(not configured[k].get('rss_id') or configured[k]['group'] != 'mfds' for k in keys):
                        raise ValueError('RSS is not configured for all selected sources')
                    max_pages = obj.get('max_pages', 2)
                    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 10:
                        raise ValueError('max_pages must be 1..10')
                    if any(configured[k]['group'] == 'industry' for k in keys) and obj.get('rights_acknowledged') is not True:
                        raise ValueError('Check media website access/usage conditions before collection')
                    with lock:
                        if job['state'] == 'running':
                            self._json({'error': 'Collection already running'}, 409)
                            return
                        with connect(db_path) as con:
                            edition = require_draft(con, active['edition'])
                        if (start, end) != (edition['period_start'], edition['period_end']):
                            raise ValueError(f'Collection period {start} ~ {end} differs from the active edition period {edition["period_start"]} ~ {edition["period_end"]}. Select [이 기간으로 회차 생성·전환] first.')
                        job.clear()
                        job.update({'state': 'running', 'results': [], 'processed': 0,
                                    'total': len(keys), 'current': None, 'error': None,
                                    'edition_id': active['edition'], 'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds')})
                        threading.Thread(target=run_collection,
                                         args=(list(keys), mode, start, end, max_pages, active['edition']),
                                         daemon=True).start()
                    self._json(job_snapshot(), 202)
                    return
                if p == '/api/edition/select':
                    target=obj.get('edition_id')
                    if not isinstance(target,str):raise ValueError('Select an edition')
                    with lock:
                        if job['state']=='running' or ai_job['state']=='running':
                            self._json({'error':'작업 중에는 회차를 전환할 수 없어.'},409)
                            return
                        with connect(db_path) as con:get_edition(con,target)
                        active['edition']=target
                    self._json({'ok':True,'edition_id':target})
                    return
                if p == '/api/confirm':
                    if obj.get('acknowledged') is not True:
                        raise ValueError('확정 전 데이터 검토 및 출력 미연결 항목 확인이 필요해.')
                    with lock:
                        if job['state']=='running' or ai_job['state']=='running':
                            self._json({'error':'수집·AI 분석 종료 후 확정해.'},409)
                            return
                        with connect(db_path) as con:
                            result=confirm(con,active['edition'],template_path,
                                           obj.get('confirmed_by'),obj.get('issue_number') or None)
                    self._json({'ok':True,**result})
                    return
                if p == '/api/ai/review':
                    with lock:
                        if ai_job['state']=='running':
                            self._json({'error':'AI 분석이 이미 진행 중이야.'},409);return
                        with connect(db_path) as con:
                            require_draft(con,active['edition'])
                            payload=review_payload(con,active['edition'],obj.get('ids'))
                        if not payload['items']:raise ValueError('AI 분석할 언론기사가 없어.')
                        if not ai_configured():raise ValueError('OPENAI_API_KEY가 없어. JSON 내보내기·가져오기를 이용해.')
                        ai_job.clear()
                        ai_job.update(state='running',processed=0,total=len(payload['items']),
                                      edition_id=active['edition'],error=None,
                                      started_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
                        threading.Thread(target=run_ai_review,args=(payload,active['edition']),daemon=True).start()
                    self._json({'ok':True,'total':len(payload['items'])},202)
                    return
                if p == '/api/ai/ask':
                    with connect(db_path) as con:
                        result=ask(con,active['edition'],obj.get('question'),obj.get('ids'))
                    self._json(result)
                    return
                if p == '/api/edition/new':
                    start, end = obj.get('start'), obj.get('end')
                    _dates(start, end)
                    count = obj.get('target', 4)
                    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100:
                        raise ValueError('Target must be an integer 0..100')
                    title = obj.get('title') or f'{start}~{end}'
                    if not isinstance(title, str) or len(title) > 120:
                        raise ValueError('Invalid edition title')
                    with lock:
                        if job['state'] == 'running':
                            self._json({'error': 'Cannot switch edition during collection'}, 409)
                            return
                        eid = obj.get('edition_id') or f'edition-{start}-{end}'
                        if not isinstance(eid,str) or not re.fullmatch(r'[0-9A-Za-z_-]{4,72}',eid):
                            raise ValueError('회차 ID는 영문·숫자·-·_ 4~72자만 가능해.')
                        with connect(db_path) as con:
                            ensure_edition(con, eid, start, end, title, count)
                            actual=get_edition(con,eid)
                            if (actual['period_start'],actual['period_end'])!=(start,end):
                                raise ValueError('해당 회차 ID에 이미 다른 기간이 연결되어 있어.')
                            if actual['status']=='draft':
                                rules = yaml.safe_load(editorial_path.read_text(encoding='utf8'))
                                prepare(con, eid, with_groups(con,rules))
                        active['edition'] = eid
                    self._json({'ok': True, 'edition_id': eid})
                    return
                with lock, connect(db_path) as con:
                    if p == '/api/review-groups/save':
                        group_id=save_group(con,obj)
                        self._json({'ok':True,'id':group_id,'groups':list_groups(con)})
                        return
                    if p == '/api/review-groups/delete':
                        delete_group(con,obj.get('id'))
                        self._json({'ok':True,'groups':list_groups(con)})
                        return
                    if p == '/api/review-groups/recalculate':
                        require_draft(con,active['edition'])
                        rules=yaml.safe_load(editorial_path.read_text(encoding='utf8'))
                        current_undated=[r['id'] for r in edition_rows(con,active['edition']) if not r['published_at']]
                        count=prepare(con,active['edition'],with_groups(con,rules),extra_ids=current_undated)
                        self._json({'ok':True,'candidates':count})
                        return
                    if p == '/api/industry/bulk':
                        result=bulk_industry(con,active['edition'],obj.get('mode'),obj.get('ids'),obj.get('value'))
                        self._json({'ok':True,**result})
                        return
                    if p == '/api/ai/import':
                        touched=import_ai(con,active['edition'],obj)
                        self._json({'ok':True,'analysed':touched})
                        return
                    if p == '/api/decision':
                        update_decision(con, active['edition'], obj['item_id'], obj['changes'])
                    elif p == '/api/top-order':
                        set_top_order(con, active['edition'], obj['ids'])
                    elif p == '/api/target':
                        require_draft(con,active['edition'])
                        num = obj['count']
                        if isinstance(num, bool) or not isinstance(num, int) or not 0 <= num <= 100:
                            raise ValueError('Target must be an integer 0..100')
                        con.execute('UPDATE editions SET top_target=? WHERE id=?', (num, active['edition']))
                        con.commit()
                    else:
                        self._json({'error': 'Unknown endpoint'}, 404)
                        return
                self._json({'ok': True})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self._json({'error': str(exc)}, 400)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', int(port)), Handler)
    print(f'편집 화면: http://127.0.0.1:{port}/  (Ctrl+C 종료)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
