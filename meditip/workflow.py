"""Issue lifecycle: source period != issue number; confirmation != delivery."""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from .db import edition_rows, get_edition


def week_label(start, end):
    """ISO week only for a full Mon-Sun period, otherwise explicit custom range."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    iso = first.isocalendar()
    if first.weekday() == 0 and (last-first).days == 6:
        return f'{iso.year}-W{iso.week:02d}'
    return f'{start} ~ {end} (사용자 지정)'


def require_draft(con, edition_id):
    edition = get_edition(con, edition_id)
    if edition['status'] != 'draft':
        raise ValueError('확정된 회차는 수정할 수 없어. 확정본을 보존하고 새 회차에서 작업해.')
    return edition


def snapshot(con, edition_id, confirmed_at=None, confirmed_by=None):
    ed = get_edition(con, edition_id)
    rows = edition_rows(con, edition_id)
    if confirmed_at:
        ed.update(status='confirmed',confirmed_at=confirmed_at,confirmed_by=confirmed_by)
    from .render import top_output_rows
    top_output_ids=[x['id'] for x in top_output_rows(rows,ed['top_target'])]
    # Include every decision and original metadata available at confirmation time.
    return {'schema_version':'meditip-issue-snapshot-1','edition':ed,
            'week_label':week_label(ed['period_start'], ed['period_end']),
            'items':rows,'top_output_ids':top_output_ids}


def confirm(con, edition_id, template_path, confirmed_by, issue_number=None):
    """Transactional one-time confirmation storing both inspectable JSON and immutable HTML."""
    from .render import render, top_output_rows
    ed = require_draft(con, edition_id)
    if not isinstance(confirmed_by, str) or not 1 <= len(confirmed_by.strip()) <= 80:
        raise ValueError('확정 담당자 이름을 입력해.')
    if issue_number is not None:
        if not isinstance(issue_number,str) or not re.fullmatch(r'[0-9A-Za-z가-힣_-]{1,30}',issue_number):
            raise ValueError('회차 번호는 1~30자의 문자·숫자·-·_만 사용할 수 있어.')
        exists=con.execute("SELECT id FROM editions WHERE issue_number=? AND id<>?",(issue_number,edition_id)).fetchone()
        if exists:raise ValueError('다른 회차에 사용 중인 회차 번호야.')
    from .company import company_output_rows
    rows=edition_rows(con,edition_id)
    if not rows:
        raise ValueError('기사가 없는 회차는 확정할 수 없어.')
    if not any(x['include_detail'] for x in rows) and not company_output_rows(rows) and not top_output_rows(rows, ed['top_target']):
        raise ValueError('수록하거나 주요 뉴스로 선정된 기사가 없어 확정할 수 없어.')
    when=datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute('UPDATE editions SET issue_number=? WHERE id=?',(issue_number,edition_id))
        html=render(con,edition_id,template_path,final=True)
        raw=json.dumps(snapshot(con,edition_id,when,confirmed_by.strip()),ensure_ascii=False,sort_keys=True)
        sha=hashlib.sha256(html.encode('utf8')).hexdigest()
        con.execute('''INSERT INTO edition_confirmations(edition_id,confirmed_at,confirmed_by,issue_number,html,raw_json,html_sha256)
                       VALUES(?,?,?,?,?,?,?)''',(edition_id,when,confirmed_by.strip(),issue_number,html,raw,sha))
        con.execute('''UPDATE editions SET status='confirmed',confirmed_at=?,confirmed_by=?,issue_number=? WHERE id=?''',
                (when,confirmed_by.strip(),issue_number,edition_id))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {'edition_id':edition_id,'status':'confirmed','confirmed_at':when,
            'confirmed_by':confirmed_by.strip(),'issue_number':issue_number,'html_sha256':sha}


def confirmed_html(con, edition_id):
    row=con.execute('SELECT html FROM edition_confirmations WHERE edition_id=?',(edition_id,)).fetchone()
    return row['html'] if row else None


def confirm_details(con,edition_id):
    row=con.execute('SELECT edition_id,confirmed_at,confirmed_by,issue_number,html_sha256 FROM edition_confirmations WHERE edition_id=?',(edition_id,)).fetchone()
    return dict(row) if row else None
