"""Local-only editorial UI with CSRF token, SQLite persistence and HTML export."""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .db import connect, edition_rows, get_edition
from .edition import update_decision, set_top_order
from .render import render


def serve(db_path,template_path,editor_path,edition_id,port=8765):
    token=secrets.token_urlsafe(32)
    editor=Path(editor_path).read_text(encoding='utf8')
    template_path=str(template_path)
    class Handler(BaseHTTPRequestHandler):
        def _respond(self,status,body,content_type='application/json; charset=utf-8',download=None):
            if isinstance(body,str):body=body.encode('utf8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'self'")
            if download:self.send_header('Content-Disposition',f'attachment; filename="{download}"')
            self.end_headers();self.wfile.write(body)
        def _json(self,obj,status=200):self._respond(status,json.dumps(obj,ensure_ascii=False).encode('utf8'))
        def do_GET(self):
            p=urlsplit(self.path)
            try:
                if p.path=='/':
                    # Token is only delivered from localhost, and required on mutating requests.
                    self._respond(200,editor.replace('__LOCAL_TOKEN__',token),'text/html; charset=utf-8');return
                if p.path=='/api/edition':
                    with connect(db_path) as c:
                        edition=get_edition(c,edition_id);items=edition_rows(c,edition_id)
                        runs=[dict(r) for r in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 30')]
                    self._json({'edition':edition,'items':items,'runs':runs});return
                if p.path=='/export/html':
                    with connect(db_path) as c:html=render(c,edition_id,template_path)
                    self._respond(200,html,'text/html; charset=utf-8',download=f'newsletter_{edition_id}.html');return
                if p.path=='/export/json':
                    with connect(db_path) as c:obj={'edition':get_edition(c,edition_id),'items':edition_rows(c,edition_id)}
                    self._respond(200,json.dumps(obj,ensure_ascii=False,indent=2),'application/json; charset=utf-8',download=f'newsletter_{edition_id}.json');return
                self._json({'error':'Not found'},404)
            except Exception as e:self._json({'error':str(e)},400)
        def do_POST(self):
            if self.headers.get('X-Local-Token')!=token or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                self._json({'error':'Unauthorized local edit'},403);return
            origin=self.headers.get('Origin','')
            if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                self._json({'error':'Unexpected Origin'},403);return
            n=int(self.headers.get('Content-Length','0') or 0)
            if n<=0 or n>50_000:self._json({'error':'Bad payload size'},400);return
            try:
                obj=json.loads(self.rfile.read(n)); p=urlsplit(self.path).path
                with connect(db_path) as c:
                    if p=='/api/decision':
                        update_decision(c,edition_id,obj['item_id'],obj['changes'])
                    elif p=='/api/top-order':set_top_order(c,edition_id,obj['ids'])
                    elif p=='/api/target':
                        num=obj['count']
                        if not isinstance(num,int) or not 0<=num<=100:raise ValueError('Target must be an integer 0..100')
                        c.execute('UPDATE editions SET top_target=? WHERE id=?',(num,edition_id));c.commit()
                    else:raise ValueError('Unknown endpoint')
                self._json({'ok':True})
            except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:self._json({'error':str(e)},400)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',int(port)),Handler)
    print(f'편집 화면: http://127.0.0.1:{port}/  (Ctrl+C 종료)')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
