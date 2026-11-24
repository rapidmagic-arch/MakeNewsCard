"""Rule recommendations and human editorial decisions are distinct."""
import json
from pathlib import Path
import yaml
from .db import edition_rows, get_edition, save_item
from .metadata_quality import title_needs_review

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

def group_proposal(row,config=None):
    """Classify a metadata candidate using user groups; never commit an editorial decision."""
    if title_needs_review(row):
        return 'industry.unclassified','review_needed',False,'제목 추출 검증 필요 · 원본 확인 후 분류',None
    text=((row['title'] or '')+' '+(row['summary_source'] or '')).casefold()
    if config is not None and 'review_groups' in config:
        groups=config['review_groups']
        strong={'industry.policy':{'약가','규제','고시','법령'},
                'industry.market':{'시장','출시','매출'},
                'industry.global':{'fda','ema','해외','글로벌'},
                'industry.rnd':{'임상','연구','신약'}}
        matches=[]
        for i,g in enumerate(groups):
            words=[str(w) for w in g['keywords'] if str(w).casefold() in text]
            section=g['target_section']
            points=sum(3 if w.casefold() in strong.get(section,set()) else 1 for w in words)
            if words:matches.append((1 if g['id'].startswith('custom-') else 0,points,len(words),-i,g,words))
        if matches:
            _,_,_,_,winner,words=max(matches,key=lambda x:x[:4])
            return (winner['target_section'],'candidate' if winner['recommend'] else 'review_needed',
                    bool(winner['recommend']),
                    '추천 그룹 '+winner['label']+' · '+', '.join(words[:5])+' · 원문 확인 필요',winner['id'])
        return 'industry.unclassified','review_needed',False,'일치하는 추천 그룹 없음 · 직접 검토 필요',None
    # Backward-compatible standalone CLI and tests when custom groups are not loaded.
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
    if not scores.get(section,0):
        return 'industry.unclassified','review_needed',False,'제목 기반 관심 키워드 일치 없음 · 직접 검토 필요',None
    matched=[t for t in hints.get(section,[]) if str(t).casefold() in text]
    return section,'candidate',True,'키워드 후보: '+', '.join(map(str,matched[:5]))+' · 원문 관련성 검토 필요',None


def industry_proposal(row,config=None):
    return group_proposal(row,config)[:4]


def proposal_for(row):
    """Imported GPT data takes precedence only when actually supplied."""
    if title_needs_review(row):
        return False, row.get('section_override') or row['section']
    imported=(row.get('ai_score') is not None or row.get('ai_reason') is not None
              or row.get('ai_section') is not None or bool(row.get('ai_summary')))
    if imported:
        return bool(row.get('ai_recommended')),row.get('ai_section') or row.get('rule_section') or row['section']
    return bool(row.get('rule_recommended')),row.get('rule_section') or row['section']


def bulk_industry(con,edition_id,mode,ids=None,value=None):
    """Explicit human action; preserve individually reviewed fields by default."""
    from .workflow import require_draft
    require_draft(con,edition_id)
    allowed={'apply_recommended','include','exclude','apply_sections','set_inclusion'}
    if mode not in allowed:raise ValueError('Unknown industry bulk operation')
    rows={r['id']:r for r in edition_rows(con,edition_id) if r['source_group']=='industry'}
    if ids is None: selected=list(rows)
    elif isinstance(ids,list) and len(ids)==len(set(ids)) and len(ids)<=5000 and set(ids)<=set(rows):selected=ids
    else:raise ValueError('Invalid industry item IDs')
    if mode == 'set_inclusion':
        if ids is None or not ids or not isinstance(value,bool):
            raise ValueError('Select specific articles and an inclusion value')
        for item_id in selected:
            con.execute('UPDATE decisions SET include_detail=?,detail_reviewed=1 WHERE edition_id=? AND item_id=?',
                        (int(value),edition_id,item_id))
        con.commit()
        return {'updated':len(selected),'protected':0,'not_recommended':0,'examined':len(selected)}
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
            # A recommended article's section is approved with the same explicit bulk action,
            # unless someone has manually reviewed the section already.
            if mode=='apply_recommended' and not row['section_reviewed']:
                _,recommended_section=proposal_for(row)
                if recommended_section in ('industry.policy','industry.market','industry.global','industry.rnd'):
                    con.execute('UPDATE decisions SET section_override=?,section_reviewed=1 WHERE edition_id=? AND item_id=?',
                                (recommended_section,edition_id,item_id))
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

def refresh_rule_proposal(con,edition_id,r,config=None):
    score,reason=rule_score(r,config)
    if r['source_group']=='industry':
        section,relevance,recommended,hint,rule_group_id=group_proposal(r,config)
        if recommended:
            # Section priority is applied to candidates, not to article inclusion.
            proposed_base=int((config or {}).get('section_priority',{}).get(
                section,KEYWORDS.get(section,(12,''))[0]))
            score=max(score,proposed_base)
        reason += ' · '+hint
    else:
        section,relevance,recommended,rule_group_id=None,None,False,None
    con.execute('''UPDATE decisions SET rule_score=?,rule_reason=?,rule_section=?,rule_relevance=?,rule_recommended=?,rule_group_id=?
               WHERE edition_id=? AND item_id=?''',
            (score,reason,section,relevance,int(recommended),rule_group_id,edition_id,r['id']))


def prepare(con,edition_id,config=None,extra_ids=None):
    from .workflow import require_draft
    edition=require_draft(con,edition_id)
    # Unknown dates must not leak into every edition. Only articles explicitly
    # observed during this edition's collection may enter as undated candidates.
    known_ids=list(dict.fromkeys(extra_ids or []))
    if len(known_ids)>5000 or any(not isinstance(x,str) for x in known_ids):
        raise ValueError('Invalid collection provenance IDs')
    sql='SELECT * FROM items WHERE published_at BETWEEN ? AND ?'
    params=[edition['period_start'],edition['period_end']]
    if known_ids:
        sql+=' OR (published_at IS NULL AND id IN ('+','.join('?' for _ in known_ids)+'))'
        params.extend(known_ids)
    rows=con.execute(sql,params).fetchall()
    for r in rows:
        score,reason=rule_score(r,config)
        include=int(r['source_group'] in ('mfds','company','clinical','treatment','drug'))
        # strict: do not auto-include unreviewed industry items
        con.execute('''INSERT OR IGNORE INTO decisions
            (edition_id,item_id,include_detail,rule_score,rule_reason)
            VALUES (?,?,?,?,?)''',(edition_id,r['id'],include,score,reason))
        refresh_rule_proposal(con,edition_id,r,config)
    con.commit()
    # TOP scores are suggestions, never automatic editorial selection.
    # Historic selected TOP entries remain in decisions unchanged.
    if rows:
        con.execute('UPDATE editions SET seeded_top=1 WHERE id=?',(edition_id,))
    con.commit()
    return len(rows)

def update_decision(con,edition_id,item_id,changes):
    from .workflow import require_draft
    require_draft(con,edition_id)
    valid={'include_detail','top_selected','top_rank','section_override','title_override','summary_override','company_selected'}
    unknown=set(changes)-valid
    if unknown:raise ValueError('Unknown editorial fields: '+','.join(sorted(unknown)))
    row=con.execute('''SELECT d.*,i.mandatory,i.source_group FROM decisions d JOIN items i ON i.id=d.item_id
                      WHERE d.edition_id=? AND d.item_id=?''',(edition_id,item_id)).fetchone()
    if row is None:raise ValueError('Edition item not found')
    if 'company_selected' in changes and (row['source_group']!='industry' or not isinstance(changes['company_selected'],bool)):
        raise ValueError('Only industry articles may be selected for company news')
    if row['mandatory'] and changes.get('include_detail') is False:
        raise ValueError('필수 수록으로 확인된 자료는 제외할 수 없어.')
    if changes.get('section_override') is not None:
        section=str(changes['section_override'])
        permitted={'mfds':'mfds.','industry':'industry.','company':'company.',
                   'clinical':'clinical.','treatment':'clinical.','drug':'drug.'}.get(row['source_group'],'')
        if not permitted or not section.startswith(permitted):
            raise ValueError('Section is incompatible with original source group')
    if 'include_detail' in changes:changes['detail_reviewed']=1
    if 'section_override' in changes:changes['section_reviewed']=1
    for flag in ('top_selected','include_detail','company_selected'):
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
    if payload.get('edition_id') not in (None,edition_id):
        raise ValueError('AI analysis belongs to another edition')
    ids=[x.get('id') for x in analyses if isinstance(x,dict)]
    if len(ids)!=len(analyses) or len(set(ids))!=len(ids):
        raise ValueError('AI analysis item IDs are duplicated or invalid')
    if payload.get('input_sha256'):
        # JSON may represent either the full exported candidate set or a selected subset.
        from .ai_review import review_payload
        hashes={review_payload(con,edition_id,ids)['input_sha256'],
                review_payload(con,edition_id)['input_sha256']}
        if payload['input_sha256'] not in hashes:
            raise ValueError('AI analysis references outdated or different source records')
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


def repair_medicaltimes_metadata(con,edition_id,item_id,expected_sha,metadata,config=None):
    """Correct one source record, version it and preserve all human editorial fields."""
    from .workflow import require_draft
    from .collect import medicaltimes_article_id, norm_date
    ed=require_draft(con,edition_id)
    row=con.execute("""SELECT i.* FROM items i JOIN decisions d ON i.id=d.item_id
                       WHERE d.edition_id=? AND i.id=?""",(edition_id,item_id)).fetchone()
    if row is None or row['source_key']!='medicaltimes' or not medicaltimes_article_id(row['url']):
        raise ValueError('현재 회차의 메디칼타임즈 기사만 원문 재확인할 수 있습니다.')
    row=dict(row)
    if row['content_sha']!=expected_sha:raise ValueError('원본이 변경되었습니다. 다시 확인하세요.')
    title=metadata['title'];published=metadata['published_at']
    if title_needs_review({'source_key':'medicaltimes','title':title}) or norm_date(published)!=published:
        raise ValueError('원문 메타데이터 검증 실패')
    changed=(title!=row['title'] or published!=row['published_at'] or row['verification']=='needs_title_review')
    prior=json.loads(row['original_metadata'] or '{}')
    updated={**prior,'title_extraction':'dedicated_detail_headline','date_extraction':'explicit_detail_publication',
             'metadata_rechecked':True}
    save_item(con,{**row,'title':title,'published_at':published,'verification':'metadata_only','original_metadata':updated})
    drafts=con.execute("""SELECT d.edition_id FROM decisions d JOIN editions e ON e.id=d.edition_id
                         WHERE d.item_id=? AND e.status='draft'""",(item_id,)).fetchall()
    repaired=dict(con.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())
    for draft in drafts:
        eid=draft['edition_id']
        refresh_rule_proposal(con,eid,repaired,config)
        if changed:
            # Old machine proposals used the previous metadata; do not treat them as current.
            # Human title/summary/section, inclusion, company and TOP decisions are untouched.
            con.execute("""UPDATE decisions SET ai_score=NULL,ai_reason=NULL,ai_summary=NULL,
                           ai_section=NULL,ai_recommended=0,ai_relevance=NULL
                           WHERE edition_id=? AND item_id=?""",(eid,item_id))
    con.commit()
    return {'title':title,'published_at':published,'changed':changed,
            'out_of_period':not ed['period_start']<=published<=ed['period_end']}
