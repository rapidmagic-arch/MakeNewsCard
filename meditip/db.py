"""SQLite persistence: raw collection is immutable by editorial decisions."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical_url(url):
    if not url: return ''
    p=urlsplit(url.strip())
    if p.scheme not in ('http','https'): raise ValueError('Only HTTP(S) URLs permitted')
    q=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
       if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urlencode(sorted(q)),''))


def record_id(source, url, event=''):
    return hashlib.sha256(f'{source}\0{canonical_url(url)}\0{event}'.encode()).hexdigest()[:24]


def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=20)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA journal_mode=WAL')
    return con


def setup(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS items (
      id TEXT PRIMARY KEY, source_key TEXT NOT NULL, source_group TEXT NOT NULL,
      section TEXT NOT NULL, source_id TEXT, url TEXT NOT NULL,
      title TEXT NOT NULL, published_at TEXT, updated_at TEXT,
      summary_source TEXT NOT NULL DEFAULT '', original_metadata TEXT NOT NULL DEFAULT '{}',
      verification TEXT NOT NULL DEFAULT 'metadata_only',
      relevance TEXT NOT NULL DEFAULT 'review_needed',
      mandatory INTEGER NOT NULL DEFAULT 0, content_sha TEXT NOT NULL,
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_item_event ON items(source_key,url,source_id);
    CREATE INDEX IF NOT EXISTS idx_items_date ON items(published_at);
    CREATE TABLE IF NOT EXISTS item_versions (
      item_id TEXT NOT NULL REFERENCES items(id), content_sha TEXT NOT NULL,
      snapshot TEXT NOT NULL, captured_at TEXT NOT NULL,
      PRIMARY KEY(item_id,content_sha)
    );
    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT NOT NULL,
      start_date TEXT, end_date TEXT, started_at TEXT NOT NULL,
      finished_at TEXT NOT NULL, status TEXT NOT NULL,
      pages_scanned INTEGER NOT NULL DEFAULT 0, records_seen INTEGER NOT NULL DEFAULT 0,
      detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS editions (
      id TEXT PRIMARY KEY, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
      title TEXT NOT NULL, top_target INTEGER NOT NULL DEFAULT 4,
      status TEXT NOT NULL DEFAULT 'draft', seeded_top INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS decisions (
      edition_id TEXT NOT NULL REFERENCES editions(id),
      item_id TEXT NOT NULL REFERENCES items(id),
      include_detail INTEGER NOT NULL DEFAULT 0,
      top_selected INTEGER NOT NULL DEFAULT 0,
      top_rank INTEGER,
      section_override TEXT,
      title_override TEXT, summary_override TEXT,
      rule_score INTEGER NOT NULL DEFAULT 0,
      rule_reason TEXT NOT NULL DEFAULT '',
      ai_score REAL, ai_reason TEXT, ai_summary TEXT, ai_section TEXT,
      ai_recommended INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(edition_id,item_id)
    );
    CREATE TABLE IF NOT EXISTS edition_confirmations (
      edition_id TEXT PRIMARY KEY REFERENCES editions(id),
      confirmed_at TEXT NOT NULL, confirmed_by TEXT NOT NULL, issue_number TEXT,
      html TEXT NOT NULL, raw_json TEXT NOT NULL, html_sha256 TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_confirmed_issue_number ON edition_confirmations(issue_number)
      WHERE issue_number IS NOT NULL;
    ''')
    # Incremental migration: never drop previously collected articles or editorial decisions.
    run_columns={row[1] for row in con.execute('PRAGMA table_info(runs)')}
    if 'edition_id' not in run_columns:
        con.execute('ALTER TABLE runs ADD COLUMN edition_id TEXT')
    con.execute('CREATE INDEX IF NOT EXISTS idx_runs_edition ON runs(edition_id,id)')
    edition_columns={row[1] for row in con.execute('PRAGMA table_info(editions)')}
    for name in ('issue_number','confirmed_at','confirmed_by','publication_date'):
        if name not in edition_columns:
            con.execute(f'ALTER TABLE editions ADD COLUMN {name} TEXT')
    if 'template_id' not in edition_columns:
        con.execute("ALTER TABLE editions ADD COLUMN template_id TEXT NOT NULL DEFAULT 'classic'")
    existing={row[1] for row in con.execute('PRAGMA table_info(decisions)')}
    for name,definition in {
        'ai_relevance':'TEXT',
        'company_rank':'INTEGER',
        'company_selected':'INTEGER NOT NULL DEFAULT 0',
        'rule_section':'TEXT',
        'rule_relevance':'TEXT',
        'rule_recommended':'INTEGER NOT NULL DEFAULT 0',
        'rule_group_id':'TEXT',
        'detail_reviewed':'INTEGER NOT NULL DEFAULT 0',
        'section_reviewed':'INTEGER NOT NULL DEFAULT 0',
    }.items():
        if name not in existing:
            con.execute(f'ALTER TABLE decisions ADD COLUMN {name} {definition}')
    # v0.1 recorded selected manual industry articles without a provenance flag.
    # Mark existing checked items as reviewed; unchecked entries were defaults,
    # and their prior manual-uncheck state cannot be reconstructed reliably.
    con.execute("""UPDATE decisions SET detail_reviewed=1
              WHERE include_detail=1 AND detail_reviewed=0
              AND item_id IN (SELECT id FROM items WHERE source_group='industry')
               AND edition_id IN (SELECT id FROM editions WHERE status='draft')""")
    con.commit()


def save_item(con, item, *, stats=None):
    url=canonical_url(item['url']); key=item['source_key']
    event=item.get('source_id','') if item.get('source_group') in ('clinical','treatment','drug') else ''
    iid=item.get('id') or record_id(key,url,event)
    now=utcnow()
    snap={'source_key':key,'source_group':item['source_group'],
          'section':item.get('section') or 'unclassified','source_id':item.get('source_id'),
          'url':url,'title':item['title'], 'published_at':item.get('published_at'),
          'updated_at':item.get('updated_at'),
          'summary_source':item.get('summary_source') or '',
          'verification':item.get('verification','metadata_only'),
          'relevance':item.get('relevance','review_needed'),
          'mandatory':bool(item.get('mandatory',False)),
          'original_metadata':item.get('original_metadata') or {}}
    raw=json.dumps(snap,sort_keys=True,ensure_ascii=False)
    sha=hashlib.sha256(raw.encode()).hexdigest()
    if stats is not None:
        previous=con.execute('SELECT content_sha FROM items WHERE id=?',(iid,)).fetchone()
        category='new' if previous is None else ('unchanged' if previous['content_sha']==sha else 'changed')
        stats[category]=stats.get(category,0)+1
    con.execute('''INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET source_key=excluded.source_key,source_group=excluded.source_group,
          section=excluded.section,source_id=excluded.source_id,url=excluded.url,
          title=excluded.title,published_at=excluded.published_at,updated_at=excluded.updated_at,
          summary_source=excluded.summary_source,original_metadata=excluded.original_metadata,
          verification=excluded.verification,relevance=excluded.relevance,mandatory=excluded.mandatory,
          content_sha=excluded.content_sha,last_seen=excluded.last_seen''',
        (iid,key,snap['source_group'],snap['section'],snap['source_id'],url,snap['title'],
         snap['published_at'],snap['updated_at'],snap['summary_source'],
         json.dumps(snap['original_metadata'],ensure_ascii=False),snap['verification'],
         snap['relevance'],int(snap['mandatory']),sha,now,now))
    con.execute('INSERT OR IGNORE INTO item_versions VALUES (?,?,?,?)',(iid,sha,raw,now))
    return iid


def log_run(con,key,start,end,status,pages,count,detail=None,edition_id=None):
    now=utcnow()
    con.execute('''INSERT INTO runs(source_key,start_date,end_date,started_at,finished_at,status,pages_scanned,records_seen,detail,edition_id)
                 VALUES(?,?,?,?,?,?,?,?,?,?)''',(key,start,end,now,now,status,pages,count,json.dumps(detail or {},ensure_ascii=False),edition_id))
    con.commit()


def ensure_edition(con,id,start,end,title=None,target=4):
    con.execute('''INSERT OR IGNORE INTO editions (id,period_start,period_end,title,top_target,status,seeded_top,created_at) VALUES (?,?,?,?,?,?,?,?)''',
                (id,start,end,title or f'{start}~{end}',target,'draft',0,utcnow()))
    con.commit()


def get_edition(con,edition_id):
    e=con.execute('SELECT * FROM editions WHERE id=?',(edition_id,)).fetchone()
    if not e: raise ValueError(f'Edition not found: {edition_id}')
    return dict(e)


def edition_rows(con,edition_id):
    e=get_edition(con,edition_id)
    return [dict(x) for x in con.execute('''SELECT i.*,d.include_detail,d.top_selected,d.top_rank,
      d.section_override,d.title_override,d.summary_override,d.rule_score,d.rule_reason,
      d.ai_score,d.ai_reason,d.ai_summary,d.ai_section,d.ai_recommended,d.ai_relevance,
      d.company_rank,d.company_selected,d.rule_section,d.rule_relevance,d.rule_recommended,d.rule_group_id,d.detail_reviewed,d.section_reviewed
      FROM decisions d JOIN items i ON i.id=d.item_id
      WHERE d.edition_id=? ORDER BY i.published_at DESC,i.title''',(edition_id,))]
