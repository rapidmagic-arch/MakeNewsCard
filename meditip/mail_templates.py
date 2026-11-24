"""Available email templates and a static, table-based Outlook card renderer.

Do not use JavaScript, externally loaded CSS, flexbox or CSS grid in email HTML.
"""
from html import escape
from urllib.parse import urlsplit
from .source_links import resolve_source_link, approval_search_url

TEMPLATES = {
    'classic': '뉴스카드 양식 v01',
    'outlook_cards': '아웃룩 양식 v01',
}
DEFAULT_TEMPLATE = 'classic'


def validate_template_id(template_id):
    if not isinstance(template_id, str) or template_id not in TEMPLATES:
        raise ValueError('지원하지 않는 뉴스레터 템플릿이야.')
    return template_id


def render_outlook_cards(con, edition_id, final=False, preview=False):
    """Static Outlook-friendly email; same editorial decisions as classic renderer."""
    from .db import edition_rows, get_edition
    from .render import GROUPS, effective, mfds_unique_sectioned, unique_for_display, approval_table, top_output_rows, source_name
    from .company import company_output_rows
    from .branding import get_branding, contact_lines

    branding=get_branding(con)
    edition = get_edition(con, edition_id)
    rows = edition_rows(con, edition_id)
    issue = ('제' + edition['issue_number'] + '호') if edition.get('issue_number') else edition['title']
    h = lambda value: escape(str(value or ''), quote=True)

    def safe_link(row):
        url,_ = resolve_source_link(row)
        if urlsplit(url).scheme not in ('http', 'https'):
            return h(effective(row, 'title'))
        return '<a href="' + h(url) + '" style="color:#12669b;text-decoration:underline">' + h(effective(row, 'title')) + '</a>'

    def item_cell(row, top=False):
        summary = effective(row, 'summary')
        title = safe_link(row)
        origin = row.get('published_at') or row.get('source_key') or '날짜 미확인'
        if not row.get('published_at') and row.get('source_group') == 'mfds':
            origin = '날짜 미확인'
        prefix = ('<p style="font-size:12px;line-height:18px;color:#65798b;margin:0 0 8px">'
                  + h(origin) + '</p>')
        body = '<p style="font-size:14px;line-height:21px;font-weight:bold;margin:0">' + title + '</p>'
        if top and summary:
            body += ('<p style="font-size:12px;line-height:19px;color:#3d5265;margin:9px 0 0">'
                     + h(summary) + '</p>')
        return prefix + body

    def section_title(title,url=None):
        return ('<tr><td style="padding:28px 20px 11px;border-bottom:2px solid #216a98">'
                '<p style="font-family:Arial,Malgun Gothic,sans-serif;font-size:18px;line-height:24px;'
                'font-weight:bold;color:#174769;margin:0">' + ('<a href="'+h(url)+'" style="color:inherit">'+h(title)+'</a>' if url else h(title)) + '</p></td></tr>')

    def article_rows(entries, label_mode='date'):
        result = []
        for row in unique_for_display(entries):
            label = row.get('published_at') if label_mode == 'date' else source_name(row)
            label = label or ('날짜 미확인' if label_mode == 'date' else '출처 미확인')
            result.append('<tr><td style="border-bottom:1px solid #e8eff5;padding:9px 20px;'
                          'font-family:Arial,Malgun Gothic,sans-serif;font-size:12px;line-height:19px;'
                          'color:#425d70"><span style="color:#63788c">' + h(label) + '</span>'
                          ' &nbsp; ' + safe_link(row) + '</td></tr>')
        return ''.join(result)

    parts = [
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>MEDiTIP 뉴스레터 - ' + h(issue) + '</title></head>',
        '<body style="margin:0;padding:0;background-color:#eef3f7">',
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="border-collapse:collapse;background-color:#eef3f7"><tr><td align="center" style="padding:24px 10px">',
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="border-collapse:collapse;max-width:760px;background-color:#ffffff;'
        'font-family:Arial,Malgun Gothic,sans-serif">',
    ]
    if not final:
        label = ('미확정 미리보기 · 메일 발송 전 검토' if preview
                 else '편집 초안 · 외부 발송 금지')
        parts.append('<tr><td style="background:#fff5d8;padding:12px 20px;font-size:12px;'
                     'color:#674c20">' + h(label) + '</td></tr>')
    parts += [
        '<tr><td style="padding:25px 20px;background-color:#193f61;color:#ffffff">',
        '<p style="font-size:12px;line-height:18px;color:#bcd4e6;margin:0 0 8px">MEDiTIP NEWSLETTER</p>',
        '<p style="font-size:23px;line-height:30px;font-weight:bold;margin:0">' + h(issue) + '</p>',
        '<p style="font-size:12px;line-height:18px;color:#d5e4ed;margin:8px 0 0">'
        + ('발행일 '+h(edition['publication_date'])+' · ' if edition.get('publication_date') else '') + '수집 기간 '+ h(edition['period_start']) + ' ~ ' + h(edition['period_end']) + '</p></td></tr>'
    ]
    tops = top_output_rows(rows, edition['top_target'])
    if tops:
        parts.append(section_title('이번 호 주요 뉴스'))
        parts.append('<tr><td style="padding:13px 14px 5px">'
                     '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                     'width="100%" style="border-collapse:collapse">')
        for idx in range(0, len(tops), 2):
            parts.append('<tr>')
            for row in tops[idx:idx+2]:
                parts.append('<td width="50%" valign="top" style="width:50%;padding:6px">'
                             '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                             'border="0" style="border-collapse:collapse;border:1px solid #d6e1eb;'
                             'background-color:#f8fbfd"><tr><td style="padding:15px;vertical-align:top">'
                             + item_cell(row, top=True) + '</td></tr></table></td>')
            if idx + 1 >= len(tops):
                parts.append('<td width="50%" style="width:50%;padding:6px">&nbsp;</td>')
            parts.append('</tr>')
        parts.append('</table></td></tr>')

    company = company_output_rows(rows)
    if company:
        parts.append(section_title('메디팁 소식'))
        parts.append(article_rows(company, 'source'))

    mfds_sectioned = list(mfds_unique_sectioned(rows))
    for key in ('mfds.guides','mfds.regulations','mfds.press','mfds.notices'):
        entries = [row for row, section in mfds_sectioned if section==key]
        if entries:
            parts.append(section_title('식약처 · ' + GROUPS[key]))
            parts.append(article_rows(entries, 'date'))

    for key in ('industry.policy','industry.market','industry.global','industry.rnd','industry.unclassified'):
        entries = [r for r in rows if r['source_group']=='industry' and r['include_detail']
                   and effective(r,'section')==key]
        if entries:
            parts.append(section_title('제약·바이오 · ' + GROUPS[key]))
            parts.append(article_rows(entries, 'source'))

    for group, title, kind in (
        ('clinical','임상시험 승인현황','clinical'),
        ('treatment','치료목적 사용승인','treatment'),
        ('drug','의약품 주간 허가현황','drug'),
    ):
        selected=[r for r in rows if r['source_group']==group and r['include_detail']]
        if selected:
            parts.append(section_title(title,approval_search_url(kind,edition['period_start'],edition['period_end'])))
            parts.append('<tr><td style="padding:12px 18px">'
                         + approval_table(selected, kind, final or preview) + '</td></tr>')

    parts.extend([
        '<tr><td style="padding:22px 20px;margin-top:25px;border-top:1px solid #d9e4ec;'
        'font-family:Arial,Malgun Gothic,sans-serif;font-size:11px;line-height:17px;'
        'color:#6a7d8c">MEDiTIP · 공개된 원문 링크를 확인해 주세요.' + ''.join('<br>'+h(line) for line in contact_lines(branding)) + '</td></tr>',
        '</table></td></tr></table></body></html>',
    ])
    return ''.join(parts)
