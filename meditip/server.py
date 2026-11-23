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
from .edition import prepare, set_top_order, update_decision
from .render import render


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
    sources_path = Path(sources_path or root/'config'/'sources.yaml')
    editorial_path = Path(editorial_path or root/'config'/'editorial.yaml')
    configured = {s['key']: s for s in source_specs(yaml.safe_load(sources_path.read_text(encoding='utf8')))}
    template_path = str(template_path)
    active = {'edition': edition_id}
    lock = threading.Lock()
    job = {'state': 'idle', 'results': [], 'processed': 0, 'total': 0, 'current': None,
           'error': None, 'edition_id': edition_id}

    def job_snapshot():
        with lock:
            return json.loads(json.dumps(job, ensure_ascii=False))

    def run_collection(keys, mode, start, end, max_pages, edition):
        try:
            for key in keys:
                spec = configured[key]
                with lock:
                    job['current'] = key
                try:
                    # A separate SQLite connection per job; no connection is shared across threads.
                    with connect(db_path) as con:
                        result = collect_source(con, spec, start, end, mode, max_pages)
                except Exception as exc:
                    result = {'source': key, 'status': 'failed', 'pages': 0, 'records': 0,
                              'issues': [type(exc).__name__ + ': ' + str(exc)[:200]]}
                    with connect(db_path) as con:
                        log_run(con, key, start, end, 'failed', 0, 0, {'mode': mode, 'issues': result['issues']})
                with lock:
                    job['results'].append(result)
                    job['processed'] += 1
            # Preserve existing manual editorial decisions; prepare updates only rule proposals.
            with connect(db_path) as con:
                rules = yaml.safe_load(editorial_path.read_text(encoding='utf8'))
                prepare(con, edition, rules)
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
                if p == '/api/edition':
                    with connect(db_path) as con:
                        edition = get_edition(con, active['edition'])
                        items = edition_rows(con, active['edition'])
                        runs = [dict(r) for r in con.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 30')]
                    self._json({'edition': edition, 'items': items, 'runs': runs})
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
                if p == '/export/html':
                    with connect(db_path) as con:
                        html = render(con, active['edition'], template_path)
                    self._respond(200, html, 'text/html; charset=utf-8',
                                  download=f'newsletter_{active["edition"]}.html')
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
                if not 0 < n <= 50_000:
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
                            edition = get_edition(con, active['edition'])
                        if (start, end) != (edition['period_start'], edition['period_end']):
                            raise ValueError('Collection dates must match the active edition. Create/select a new edition first.')
                        job.clear()
                        job.update({'state': 'running', 'results': [], 'processed': 0,
                                    'total': len(keys), 'current': None, 'error': None,
                                    'edition_id': active['edition'], 'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds')})
                        threading.Thread(target=run_collection,
                                         args=(list(keys), mode, start, end, max_pages, active['edition']),
                                         daemon=True).start()
                    self._json(job_snapshot(), 202)
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
                        eid = f'edition-{start}-{end}'
                        with connect(db_path) as con:
                            ensure_edition(con, eid, start, end, title, count)
                            rules = yaml.safe_load(editorial_path.read_text(encoding='utf8'))
                            prepare(con, eid, rules)
                        active['edition'] = eid
                    self._json({'ok': True, 'edition_id': eid})
                    return
                with connect(db_path) as con:
                    if p == '/api/decision':
                        update_decision(con, active['edition'], obj['item_id'], obj['changes'])
                    elif p == '/api/top-order':
                        set_top_order(con, active['edition'], obj['ids'])
                    elif p == '/api/target':
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
