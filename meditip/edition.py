"""Rule recommendations and human editorial decisions are distinct."""
import json
from pathlib import Path
import yaml
from .db import edition_rows, get_edition

KEYWORDS={
    'mfds.regulations':(75,'규제·고시 및 행정예고'),
    'mfds.guides':(70,'공무원지침서·민원인안내서'),
    'mfds.notices':(58,'공지·공고'),
    'mfds.press':(45,'식약처 보도자료'),
    'industry.policy':(40,'정책 동향'),
    'industry.rnd':(35,'연구개발 동향'),
    'industry.market':(30,'시장 동향'),
    'industry.global':(30,'글로벌 동향'),
}
INTEREST={'GLP-1':16,'ADC':16,'MOA':12,'교육':10,'설명회':10,'워크숍':10,'개정':12,'허가':9,'신약':8,'품질':7}

def rule_score(row, config=None):
    priorities=(config or {}).get('section_priority',{})
    fallback,reason=KEYWORDS.get(row['section'],(12,'일반 후보'))
    score=int(priorities.get(row['section'],fallback))
    interests={str(x['term']):int(x['bonus']) for x in (config or {}).get('interest_terms',[])} or INTEREST
    for key,bonus in interests.items():
        if key.casefold() in row['title'].casefold():score+=bonus;reason+=f' · {key}'
    return score,reason

def prepare(con,edition_id,config=None):
    edition=get_edition(con,edition_id)
    rows=con.execute('''SELECT * FROM items WHERE (published_at BETWEEN ? AND ?) OR published_at IS NULL''',
                     (edition['period_start'],edition['period_end'])).fetchall()
    for r in rows:
        score,reason=rule_score(r,config)
        include=int(r['source_group'] in ('mfds','company','clinical','treatment','drug'))
        # strict: do not auto-include unreviewed industry items
        con.execute('''INSERT OR IGNORE INTO decisions
            (edition_id,item_id,include_detail,rule_score,rule_reason)
            VALUES (?,?,?,?,?)''',(edition_id,r['id'],include,score,reason))
        con.execute('''UPDATE decisions SET rule_score=?,rule_reason=? WHERE edition_id=? AND item_id=?''',
                    (score,reason,edition_id,r['id']))
    con.commit()
    # Seed rule-based TOP suggestions only when no human selections exist.
    if not edition['seeded_top']:
        proposed=con.execute('''SELECT item_id FROM decisions WHERE edition_id=? ORDER BY rule_score DESC,item_id LIMIT ?''',
                             (edition_id,edition['top_target'])).fetchall()
        for i,x in enumerate(proposed,1):
            con.execute('UPDATE decisions SET top_selected=1,top_rank=? WHERE edition_id=? AND item_id=?',
                        (i,edition_id,x['item_id']))
    # An empty edition has nothing to recommend yet: allow initial suggestions
    # after the first real collection, without overwriting later human decisions.
    if rows:
        con.execute('UPDATE editions SET seeded_top=1 WHERE id=?',(edition_id,))
    con.commit()
    return len(rows)

def update_decision(con,edition_id,item_id,changes):
    valid={'include_detail','top_selected','top_rank','section_override','title_override','summary_override'}
    unknown=set(changes)-valid
    if unknown:raise ValueError('Unknown editorial fields: '+','.join(sorted(unknown)))
    row=con.execute('''SELECT d.*,i.mandatory,i.source_group FROM decisions d JOIN items i ON i.id=d.item_id
                      WHERE d.edition_id=? AND d.item_id=?''',(edition_id,item_id)).fetchone()
    if row is None:raise ValueError('Edition item not found')
    if (row['mandatory'] or row['source_group']=='mfds') and changes.get('include_detail') is False:
        raise ValueError('MFDS/mandatory source cannot be excluded from detail list; classify relevance separately')
    if changes.get('section_override') is not None:
        section=str(changes['section_override'])
        permitted={'mfds':'mfds.','industry':'industry.','company':'company.',
                   'clinical':'clinical.','treatment':'clinical.','drug':'drug.'}.get(row['source_group'],'')
        if not permitted or not section.startswith(permitted):
            raise ValueError('Section is incompatible with original source group')
    for flag in ('top_selected','include_detail'):
        if flag in changes:changes[flag]=int(bool(changes[flag]))
    if 'top_rank' in changes and changes['top_rank'] is not None:
        if not isinstance(changes['top_rank'],int) or changes['top_rank']<1:raise ValueError('rank must be a positive integer')
    for text_field in ('summary_override','title_override'):
        if text_field in changes and changes[text_field] is not None and len(changes[text_field])>2000:raise ValueError('Text too long')
    if changes:
        columns=','.join(f'{k}=?' for k in changes)
        con.execute(f'UPDATE decisions SET {columns} WHERE edition_id=? AND item_id=?',(*changes.values(),edition_id,item_id))
        con.commit()

def set_top_order(con,edition_id,ids):
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate IDs')
    available={x['id'] for x in edition_rows(con,edition_id)}
    if not set(ids).issubset(available):raise ValueError('Unknown article IDs')
    con.execute('UPDATE decisions SET top_selected=0,top_rank=NULL WHERE edition_id=?',(edition_id,))
    for i,id in enumerate(ids,1):
        con.execute('UPDATE decisions SET top_selected=1,top_rank=? WHERE edition_id=? AND item_id=?',(i,edition_id,id))
    con.commit()

def import_ai(con,edition_id,payload):
    """Only adds AI proposals; it never changes human selections or source rows."""
    rows={r['id']:r for r in edition_rows(con,edition_id)}
    analyses=payload.get('items',[])
    if not isinstance(analyses,list):raise ValueError('items must be an array')
    touched=0
    for item in analyses:
        id=item.get('id')
        if id not in rows:raise ValueError('AI output references unknown item: '+str(id))
        score=item.get('score')
        if score is not None and (not isinstance(score,(float,int)) or not 0<=score<=100):raise ValueError('score must be 0..100')
        summary=item.get('summary')
        if summary is not None and (not isinstance(summary,str) or len(summary)>2500):raise ValueError('Invalid summary')
        section=item.get('section')
        if section and not str(section).startswith({'mfds':'mfds.','industry':'industry.','company':'company.',
                 'clinical':'clinical.','treatment':'clinical.','drug':'drug.'}.get(rows[id]['source_group'],'__invalid__')):
            raise ValueError('AI section incompatible with source group: '+str(id))
        con.execute('''UPDATE decisions SET ai_score=?,ai_reason=?,ai_summary=?,ai_section=?,ai_recommended=?
                     WHERE edition_id=? AND item_id=?''',
                    (score,item.get('reason'),summary,item.get('section'),int(bool(item.get('recommended',False))),edition_id,id))
        touched+=1
    con.commit()
    return touched
