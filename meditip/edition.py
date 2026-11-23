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


# Broad candidate discovery only: a title match is NOT a verified editorial judgment.
INDUSTRY_HINTS={
  'industry.policy': ('규제','고시','법령','식약처','심사','약가','급여','허가','가이드라인','보험등재'),
  'industry.market': ('시장','공급','출시','계약','투자','인수','매출','파트너십','moa','mou'),
  'industry.global': ('fda','ema','유럽','미국','일본','해외','글로벌','수출','국제'),
  'industry.rnd': ('임상','연구','개발','신약','glp-1','adc','항체','바이오','후보물질','치료제'),
}

def industry_proposal(row,config=None):
    """Mechanical review suggestion using headline/available source summary only."""
    text=((row['title'] or '')+' '+(row['summary_source'] or '')).casefold()
    hints=(config or {}).get('industry_section_keywords') or INDUSTRY_HINTS
    strong={'industry.policy':{'약가','규제','고시','법령'},
            'industry.market':{'시장','출시','매출'},
            'industry.global':{'fda','ema','해외','글로벌'},
            'industry.rnd':{'임상','연구','신약'}}
    scores={k:sum((3 if str(term).casefold() in strong.get(k,set()) else 1)
                  for term in words if str(term).casefold() in text)
            for k,words in hints.items() if k in INDUSTRY_HINTS}
    order=list(INDUSTRY_HINTS)
    section=max(order,key=lambda key:(scores.get(key,0),-order.index(key)))
    count=scores.get(section,0)
    if not count:
        return 'industry.unclassified','review_needed',False,'제목 기반 관심 키워드 일치 없음 · 직접 검토 필요'
    matched=[t for t in hints.get(section,[]) if str(t).casefold() in text]
    return section,'candidate',True,'키워드 후보: '+', '.join(map(str,matched[:5]))+' · 원문 관련성 검토 필요'


def proposal_for(row):
    """Imported GPT data takes precedence only when actually supplied."""
    imported=(row.get('ai_score') is not None or row.get('ai_reason') is not None
              or row.get('ai_section') is not None or bool(row.get('ai_summary')))
    if imported:
        return bool(row.get('ai_recommended')),row.get('ai_section') or row.get('rule_section') or row['section']
    return bool(row.get('rule_recommended')),row.get('rule_section') or row['section']


def bulk_industry(con,edition_id,mode,ids=None):
    """Explicit human action; preserve individually reviewed fields by default."""
    from .workflow import require_draft
    require_draft(con,edition_id)
    allowed={'apply_recommended','include','exclude','apply_sections'}
    if mode not in allowed:raise ValueError('Unknown industry bulk operation')
    rows={r['id']:r for r in edition_rows(con,edition_id) if r['source_group']=='industry'}
    if ids is None: selected=list(rows)
    elif isinstance(ids,list) and len(ids)==len(set(ids)) and len(ids)<=5000 and set(ids)<=set(rows):selected=ids
    else:raise ValueError('Invalid industry item IDs')
    updated=0;reviewed=0;not_recommended=0
    for item_id in selected:
        row=rows[item_id]
        if mode=='apply_sections':
            if row['section_reviewed']:
                reviewed+=1;continue
            _,section=proposal_for(row)
            if not section.startswith('industry.') or section=='industry.unclassified':
                not_recommended+=1;continue
            con.execute('UPDATE decisions SET section_override=?,section_reviewed=1 WHERE edition_id=? AND item_id=?',
                        (section,edition_id,item_id))
        else:
            if row['detail_reviewed']:
                reviewed+=1;continue
            rec,_=proposal_for(row)
            if mode=='apply_recommended' and not rec:
                not_recommended+=1;continue
            include=(mode!='exclude')
            con.execute('UPDATE decisions SET include_detail=?,detail_reviewed=1 WHERE edition_id=? AND item_id=?',
                        (int(include),edition_id,item_id))
        updated+=1
    con.commit()
    return {'updated':updated,'protected':reviewed,'not_recommended':not_recommended,'examined':len(selected)}

def rule_score(row, config=None):
    priorities=(config or {}).get('section_priority',{})
    fallback,reason=KEYWORDS.get(row['section'],(12,'일반 후보'))
    score=int(priorities.get(row['section'],fallback))
    interests={str(x['term']):int(x['bonus']) for x in (config or {}).get('interest_terms',[])} or INTEREST
    for key,bonus in interests.items():
        if key.casefold() in row['title'].casefold():score+=bonus;reason+=f' · {key}'
    return score,reason

def prepare(con,edition_id,config=None):
    from .workflow import require_draft
    edition=require_draft(con,edition_id)
    rows=con.execute('''SELECT * FROM items WHERE (published_at BETWEEN ? AND ?) OR published_at IS NULL''',
                     (edition['period_start'],edition['period_end'])).fetchall()
    for r in rows:
        score,reason=rule_score(r,config)
        include=int(r['source_group'] in ('mfds','company','clinical','treatment','drug'))
        # strict: do not auto-include unreviewed industry items
        con.execute('''INSERT OR IGNORE INTO decisions
            (edition_id,item_id,include_detail,rule_score,rule_reason)
            VALUES (?,?,?,?,?)''',(edition_id,r['id'],include,score,reason))
        if r['source_group']=='industry':
            section,relevance,recommended,hint=industry_proposal(r,config)
            if recommended:
                # Section priority is applied to candidates, not to article inclusion.
                proposed_base=int((config or {}).get('section_priority',{}).get(
                    section,KEYWORDS.get(section,(12,''))[0]))
                score=max(score,proposed_base)
            reason += ' · '+hint
        else:
            section,relevance,recommended=None,None,False
        con.execute('''UPDATE decisions SET rule_score=?,rule_reason=?,rule_section=?,rule_relevance=?,rule_recommended=?
                       WHERE edition_id=? AND item_id=?''',
                    (score,reason,section,relevance,int(recommended),edition_id,r['id']))
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
    from .workflow import require_draft
    require_draft(con,edition_id)
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
    if 'include_detail' in changes:changes['detail_reviewed']=1
    if 'section_override' in changes:changes['section_reviewed']=1
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
    from .workflow import require_draft
    require_draft(con,edition_id)
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate IDs')
    available={x['id'] for x in edition_rows(con,edition_id)}
    if not set(ids).issubset(available):raise ValueError('Unknown article IDs')
    con.execute('UPDATE decisions SET top_selected=0,top_rank=NULL WHERE edition_id=?',(edition_id,))
    for i,id in enumerate(ids,1):
        con.execute('UPDATE decisions SET top_selected=1,top_rank=? WHERE edition_id=? AND item_id=?',(i,edition_id,id))
    con.commit()

def import_ai(con,edition_id,payload):
    """Only adds AI proposals; it never changes human selections or source rows."""
    from .workflow import require_draft
    require_draft(con,edition_id)
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
        relevance=item.get('relevance')
        if relevance is not None and relevance not in ('relevant','irrelevant','review_needed'):
            raise ValueError('Invalid AI relevance value')
        section=item.get('section')
        if section and not str(section).startswith({'mfds':'mfds.','industry':'industry.','company':'company.',
                 'clinical':'clinical.','treatment':'clinical.','drug':'drug.'}.get(rows[id]['source_group'],'__invalid__')):
            raise ValueError('AI section incompatible with source group: '+str(id))
        con.execute('''UPDATE decisions SET ai_score=?,ai_reason=?,ai_summary=?,ai_section=?,ai_recommended=?,ai_relevance=?
                     WHERE edition_id=? AND item_id=?''',
                    (score,item.get('reason'),summary,item.get('section'),int(bool(item.get('recommended',False))),relevance,edition_id,id))
        touched+=1
    con.commit()
    return touched
