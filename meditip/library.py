"""Read-only newsletter library; viewing an archive never switches active editions."""


def library_page(con, status='confirmed', search='', page=1, page_size=12):
    if status not in ('confirmed', 'draft', 'all'):
        raise ValueError('Unknown library status')
    if not isinstance(search, str) or len(search) > 100:
        raise ValueError('Invalid library search')
    if type(page) is not int or not 1 <= page <= 100000:
        raise ValueError('Invalid library page')
    if type(page_size) is not int or not 1 <= page_size <= 24:
        raise ValueError('Invalid library page size')
    filters=[];values=[]
    if status != 'all':
        filters.append('e.status = ?');values.append(status)
    if search.strip():
        # Literal search, not SQL wildcard expansion.
        term=search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        filters.append("(e.title LIKE ? ESCAPE '\\' OR e.issue_number LIKE ? ESCAPE '\\' OR e.period_start LIKE ? ESCAPE '\\')")
        values.extend([f'%{term}%']*3)
    where=' WHERE '+' AND '.join(filters) if filters else ''
    total=con.execute('SELECT COUNT(*) FROM editions e'+where,values).fetchone()[0]
    sql='''SELECT e.id,e.title,e.period_start,e.period_end,e.status,e.issue_number,e.confirmed_at,e.created_at,
                 (SELECT COUNT(*) FROM decisions d WHERE d.edition_id=e.id) AS candidates,
                 (SELECT COUNT(*) FROM decisions d WHERE d.edition_id=e.id AND d.include_detail=1) AS included,
                 (SELECT COUNT(*) FROM decisions d WHERE d.edition_id=e.id AND d.top_selected=1) AS top_selected,
                 CASE WHEN c.edition_id IS NULL THEN 0 ELSE 1 END AS snapshot_available
           FROM editions e LEFT JOIN edition_confirmations c ON c.edition_id=e.id'''+where+'''
           ORDER BY CASE WHEN e.status='confirmed' THEN 0 ELSE 1 END,
                    COALESCE(e.confirmed_at,e.created_at) DESC,e.id DESC LIMIT ? OFFSET ?'''
    entries=[dict(row) for row in con.execute(sql,[*values,page_size,(page-1)*page_size])]
    return {'items':entries,'total':total,'page':page,'page_size':page_size,'pages':max(1,(total+page_size-1)//page_size), 'status':status}


def archived_html(con, edition_id):
    if not isinstance(edition_id,str) or not edition_id or len(edition_id)>120:
        raise ValueError('Invalid edition')
    row=con.execute("""SELECT c.html FROM edition_confirmations c JOIN editions e ON e.id=c.edition_id
                       WHERE c.edition_id=? AND e.status='confirmed'""",(edition_id,)).fetchone()
    return row['html'] if row else None
