"""Offline integration coverage for the local collection UI API."""
import http.client
import json
import re
import socket
import threading
import time
from pathlib import Path

import pytest

from meditip.db import connect, edition_rows, ensure_edition, log_run, save_item, setup
from meditip.edition import prepare
from meditip.server import _dates
import meditip.server as server_module

ROOT = Path(__file__).resolve().parents[1]


def test_date_boundaries():
    assert _dates('2026-11-16', '2026-11-22')[0].isoformat() == '2026-11-16'
    for start, end in [('11/16/2026', '2026-11-22'), ('2026-11-22', '2026-11-16'),
                       ('2026-02-30', '2026-03-01'), ('2025-01-01', '2026-12-31')]:
        with pytest.raises(ValueError):
            _dates(start, end)


def test_prepare_empty_then_collect_suggests(tmp_path):
    db = tmp_path/'test.db'
    with connect(db) as c:
        setup(c)
        ensure_edition(c, 'new', '2026-11-16', '2026-11-22')
        assert prepare(c, 'new') == 0
        assert not c.execute('SELECT seeded_top FROM editions WHERE id="new"').fetchone()[0]
        save_item(c, {'source_key': 'press', 'source_group': 'mfds', 'section': 'mfds.press',
                      'title': '확인용 테스트 기사', 'url': 'https://www.mfds.go.kr/brd/m_99/view.do?seq=555',
                      'published_at': '2026-11-17'})
        assert prepare(c, 'new') == 1
        assert edition_rows(c, 'new')[0]['top_selected'] == 0


def test_ui_collect_and_new_edition_without_network(tmp_path, monkeypatch):
    db = tmp_path/'test.db'
    with connect(db) as c:
        setup(c)
        ensure_edition(c, 'demo', '2026-11-16', '2026-11-22')

    def fake_collect(con, spec, start, end, mode='board', max_pages=2, edition_id=None):
        save_item(con, {'source_key': spec['key'], 'source_group': 'mfds',
                        'section': spec['html_section'], 'url': 'https://www.mfds.go.kr/brd/m_99/view.do?seq=555',
                        'title': '테스트 보도자료', 'published_at': start, 'verification': 'metadata_only'})
        con.commit()
        log_run(con, spec['key'], start, end, 'partial', 1, 1, {'test': 'fake offline collection'}, edition_id=edition_id)
        return {'source': spec['key'], 'status': 'partial', 'records': 1, 'pages': 1,
                'issues': ['Offline fixture; no completeness claim']}

    monkeypatch.setattr(server_module, 'collect_source', fake_collect)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    thread = threading.Thread(target=server_module.serve,
                              args=(db, ROOT/'templates'/'892_slots_original.html',
                                    ROOT/'editor.html', 'demo', port),
                              daemon=True)
    thread.start()

    def req(method, url, data=None, token=None):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        payload = json.dumps(data).encode() if data is not None else None
        headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{port}'}
        if token:
            headers['X-Local-Token'] = token
        c.request(method, url, body=payload, headers=headers)
        r = c.getresponse()
        status, body = r.status, r.read().decode('utf8')
        c.close()
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, body

    for _ in range(30):
        try:
            status, html = req('GET', '/')
            if status == 200:
                break
        except OSError:
            time.sleep(.05)
    else:
        pytest.fail('local HTTP server did not start')

    token = re.search(r"const TOKEN='([^']+)'", html).group(1)
    assert '실제 자료 수집' in html
    assert req('GET', '/api/sources')[0] == 200
    assert req('POST', '/api/collect', {'sources': ['press']})[0] == 403
    assert req('POST', '/api/collect', {'sources': ['not-configured'], 'start': '2026-11-16', 'end': '2026-11-22'}, token)[0] == 400
    status, error = req('POST', '/api/collect', {'sources': ['press'], 'start': '2026-11-20', 'end': '2026-11-22'}, token)
    assert status == 400
    assert '2026-11-20' in error['error'] and '2026-11-16' in error['error']
    assert req('POST', '/api/collect', {'sources': ['dailypharm'], 'start': '2026-11-16', 'end': '2026-11-22'}, token)[0] == 400
    status, edition = req('POST', '/api/edition/new', {'start': '2026-11-23', 'end': '2026-11-29'}, token)
    assert status == 200 and edition['edition_id'] == 'edition-2026-11-23-2026-11-29'
    status, result = req('POST', '/api/collect', {'sources': ['press'], 'start': '2026-11-23', 'end': '2026-11-29', 'method': 'board', 'max_pages': 2}, token)
    assert status == 202
    for _ in range(100):
        status, job = req('GET', '/api/collection')
        if job['state'] != 'running':
            break
        time.sleep(.03)
    assert job['state'] == 'finished' and job['processed'] == 1
    assert job['results'][0]['status'] == 'partial'
    status, e = req('GET', '/api/edition')
    assert e['edition']['period_start'] == '2026-11-23'
    assert len(e['items']) == 1 and e['items'][0]['top_selected'] == 0
    assert len(e['runs']) == 1 and e['runs'][0]['status'] == 'partial'
    assert req('GET', '/export/html')[0] == 200
