"""No-network MFDS source adapter tests: date filters, identity, partial audit."""
from urllib.parse import parse_qs, urlparse

from meditip.collect import collect_source, mfds_canonical_link, mfds_post_key
from meditip.db import connect, setup


class FakeResponse:
    def __init__(self, url, data):
        self.url = url
        self.content = data.encode('utf-8') if isinstance(data, str) else data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, rss_fail=False):
        self.calls = []
        self.rss_fail = rss_fail

    def get(self, url, **_):
        self.calls.append(url)
        if 'rss/brd.do' in url:
            if self.rss_fail:
                raise ConnectionError('RSS unavailable')
            return FakeResponse(url, '''<rss version="2.0"><channel>
            <item><title>Official first item</title><link>https://www.mfds.go.kr/brd/m_99/view.do?seq=101</link><pubDate>Tue, 17 Nov 2026 08:00:00 +0900</pubDate></item>
            <item><title>Missing board item</title><link>https://www.mfds.go.kr/brd/m_99/view.do?seq=999</link><pubDate>Wed, 18 Nov 2026 08:00:00 +0900</pubDate></item>
            </channel></rss>''')
        page = parse_qs(urlparse(url).query)['page'][0]
        if page == '1':
            return FakeResponse(url, '''<table>
                <tr><td>2026-11-17</td><td><a href="/brd/m_99/view.do?seq=101&amp;page=1">Official first item</a></td></tr>
                <tr><td>2026-11-17</td><td><a href="/brd/m_99/view.do?page=2&amp;seq=101">Official first item</a></td></tr>
                <tr><td>2026-11-01</td><td><a href="/brd/m_99/view.do?seq=88">Older item ignored</a></td></tr>
            </table>''')
        return FakeResponse(url, '''<table>
            <tr><td>2026-11-18</td><td><a href="/brd/m_99/view.do?seq=102">Second official item</a></td></tr>
            <tr><td>2026-11-17</td><td><a href="/brd/m_99/view.do?seq=101">Official first item</a></td></tr>
        </table>''')


def test_mfds_identity_removes_search_query_only_for_known_board():
    u = 'https://www.mfds.go.kr/brd/m_99/view.do?seq=101&page=4&srchFr=2026-11-16'
    assert mfds_post_key(u) == ('99', '101')
    assert mfds_canonical_link(u) == 'https://www.mfds.go.kr/brd/m_99/view.do?seq=101'
    other = 'https://www.mfds.go.kr/brd/m_99/view.do?foo=4'
    assert mfds_post_key(other) is None and mfds_canonical_link(other) == other


def test_date_pagination_dedup_and_rss_audit(tmp_path):
    session = FakeSession()
    spec = {'key':'press', 'group':'mfds', 'url':'https://www.mfds.go.kr/brd/m_99/list.do',
            'html_section':'mfds.press', 'rss_id':'ntc0021'}
    with connect(tmp_path/'news.db') as c:
        setup(c)
        report=collect_source(c,spec,'2026-11-16','2026-11-22','board',max_pages=2,delay=0,session=session)
        assert report['status']=='partial'
        assert report['records']==2 and report['duplicate_rows']==2
        assert report['rss_crosscheck']['rss_not_on_board_count']==1
        rows=c.execute('SELECT url, source_id FROM items ORDER BY url').fetchall()
        assert [r['source_id'] for r in rows]==['101','102']
        assert all('page=' not in r['url'] for r in rows)
        assert report['pages']==2
        for page in session.calls[:2]:
            q=parse_qs(urlparse(page).query)
            assert q['srchFr']==['2026-11-16'] and q['srchTo']==['2026-11-22']
        # Repeat scan must not insert new rows despite URL pagination differences.
        collect_source(c,spec,'2026-11-16','2026-11-22','board',max_pages=2,delay=0,session=FakeSession())
        assert c.execute('SELECT COUNT(*) FROM items').fetchone()[0] == 2


def test_rss_failure_does_not_discard_board_records(tmp_path):
    spec = {'key':'press', 'group':'mfds', 'url':'https://www.mfds.go.kr/brd/m_99/list.do',
            'html_section':'mfds.press', 'rss_id':'ntc0021'}
    with connect(tmp_path/'news.db') as c:
        setup(c)
        report=collect_source(c,spec,'2026-11-16','2026-11-22',max_pages=1,session=FakeSession(rss_fail=True))
        assert report['records']==1
        assert report['rss_crosscheck']['status']=='failed'
        assert c.execute('SELECT COUNT(*) FROM items').fetchone()[0] == 1
        assert report['status']=='partial'


def test_absent_rss_mapping_is_explicit(tmp_path):
    spec = {'key':'enacted_notices','group':'mfds', 'url':'https://www.mfds.go.kr/brd/m_99/list.do',
            'html_section':'mfds.regulations'}
    with connect(tmp_path/'news.db') as c:
        setup(c)
        report=collect_source(c,spec,'2026-11-16','2026-11-22',max_pages=1,session=FakeSession())
        assert report['rss_crosscheck']['status']=='not_configured'
        assert report['records']==1
