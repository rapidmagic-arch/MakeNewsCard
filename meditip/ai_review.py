"""One review engine for HTTP and CLI. No API call without explicit user action.

The raw source remains untouched. Responses are proposals, never publishing actions.
"""
import copy
import hashlib
import json
import os
import requests
from .db import edition_rows, get_edition

API_URL='https://api.openai.com/v1/responses'
SCHEMA={
    'type':'object','additionalProperties':False,
    'properties':{'items':{'type':'array','items':{'type':'object','additionalProperties':False,
        'properties':{
            'id':{'type':'string'},'section':{'type':'string','enum':['mfds.guides','mfds.regulations','mfds.press','mfds.notices','industry.policy','industry.market','industry.global','industry.rnd','industry.unclassified','company.news','clinical.approval','clinical.treatment','drug.approvals']},
            'score':{'type':'number','minimum':0,'maximum':100},'recommended':{'type':'boolean'},
            'relevance':{'type':'string','enum':['relevant','irrelevant','review_needed']},
            'reason':{'type':'string'},'summary':{'type':'string'}},
        'required':['id','section','score','recommended','relevance','reason','summary']}}},
    'required':['items']}

# Shared exact values: source types are not editorial publication categories.
SECTION_BY_GROUP={
    'mfds':('mfds.guides','mfds.regulations','mfds.press','mfds.notices'),
    'industry':('industry.policy','industry.market','industry.global','industry.rnd','industry.unclassified'),
    'company':('company.news',),'clinical':('clinical.approval',),
    'treatment':('clinical.treatment',),'drug':('drug.approvals',),
}
def allowed_sections(group):
    return SECTION_BY_GROUP.get(group,())

def candidate_hash(items):
    raw=json.dumps(items,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(raw.encode('utf8')).hexdigest()

def candidates(con,edition_id,ids=None):
    get_edition(con,edition_id)
    rows=edition_rows(con,edition_id)
    if ids is not None:
        if not isinstance(ids,list) or len(ids)>1000 or len(ids)!=len(set(ids)):
            raise ValueError('Invalid review selection')
        if any(not isinstance(x,str) for x in ids):raise ValueError('Invalid selected article ID')
        known={x['id'] for x in rows}
        if not set(ids)<=known:raise ValueError('Unknown selected article')
        rows=[x for x in rows if x['id'] in ids]
    return rows


def review_payload(con,edition_id,ids=None):
    rows=candidates(con,edition_id,ids)
    items=[{'id':x['id'],'title':x['title'],'url':x['url'],'published_at':x['published_at'],
            'source_key':x['source_key'],'source_group':x['source_group'],'section':x['section'],'verification':x['verification'],
            'summary_source':x.get('summary_source') or ''} for x in rows]
    return {'schema_version':'meditip-ai-candidate-1','edition_id':edition_id,
            'input_sha256':candidate_hash(items),'items':items,
            'notice':'Metadata may lack full article text; never assert full-text verification.'}


def configured():
    return bool(os.getenv('OPENAI_API_KEY'))


def _response_text(obj):
    for item in obj.get('output',[]):
        for content in item.get('content',[]):
            if content.get('type')=='output_text' and isinstance(content.get('text'),str):
                return content['text']
    if isinstance(obj.get('output_text'),str):return obj['output_text']
    raise ValueError('AI API returned no output text')


def _call_api(messages, schema=None, model=None):
    key=os.getenv('OPENAI_API_KEY')
    if not key:raise ValueError('OPENAI_API_KEY가 설정되지 않았어. JSON 수동 분석 방식을 이용해.')
    model=model or os.getenv('OPENAI_MODEL','gpt-4.1-mini')
    data={'model':model,'input':messages,'store':False,'max_output_tokens':4500}
    if schema is not None:
        data['text']={'format':{'type':'json_schema','name':'newsletter_review','strict':True,'schema':schema}}
    r=requests.post(API_URL,json=data,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},timeout=(10,90))
    r.raise_for_status()
    return _response_text(r.json())


def analyze(payload,model=None,allow_partial=False,on_progress=None):
    """Source-homogeneous batches. A failed response never becomes a publishing decision."""
    if not os.getenv('OPENAI_API_KEY'):
        raise ValueError('OPENAI_API_KEY가 설정되지 않았어. JSON 수동 분석 방식을 이용해.')
    items=payload['items']
    if not items:return {'items':[]}
    groups={}
    for row in items:
        if not allowed_sections(row['source_group']):
            raise ValueError('Unsupported source group')
        groups.setdefault(row['source_group'],[]).append(row)
    all_results=[];failures=[];processed=0
    for group,rows in groups.items():
        schema=copy.deepcopy(SCHEMA)
        allowed=allowed_sections(group)
        schema['properties']['items']['items']['properties']['section']['enum']=list(allowed)
        for index in range(0,len(rows),20):
            batch=rows[index:index+20]
            ids=[x['id'] for x in batch]
            instruction=('한국어 제약·바이오 뉴스레터 편집 보조다. 메타데이터만 제공하므로 제목에서 확인되지 않은 사실을 생성하지 마. '
                         '입력의 각 id에 대해 정확히 하나씩 반환. 분류값은 '+', '.join(allowed)+' 중 하나만 사용. '
                         '추천 이유·요약은 검증 전 제안으로 작성하고 미확인 사항은 reason에 명시해.')
            try:
                output=json.loads(_call_api([{'role':'system','content':instruction},
                                             {'role':'user','content':json.dumps(batch,ensure_ascii=False)}],schema,model))
                if not isinstance(output,dict) or not isinstance(output.get('items'),list):
                    raise ValueError('Invalid AI response schema')
                results=output['items']
                if any(not isinstance(x,dict) or not isinstance(x.get('id'),str) for x in results):
                    raise ValueError('Invalid AI response item')
                counts={}
                for x in results:counts[x['id']]=counts.get(x['id'],0)+1
                if set(counts)-set(ids):raise ValueError('AI returned foreign item IDs')
                valid={}
                for result in results:
                    rid=result['id'];score=result.get('score')
                    if (counts[rid]!=1 or result.get('section') not in allowed
                        or result.get('relevance') not in ('relevant','irrelevant','review_needed')
                        or not isinstance(result.get('recommended'),bool)
                        or isinstance(score,bool) or not isinstance(score,(int,float)) or not 0<=score<=100
                        or not isinstance(result.get('reason'),str) or len(result['reason'])>2500
                        or not isinstance(result.get('summary'),str) or len(result['summary'])>2500):
                        continue
                    valid[rid]=result
                invalid=[rid for rid in ids if rid not in valid]
                if invalid and not allow_partial:
                    raise ValueError('AI returned missing, duplicated or invalid classification data')
                all_results.extend(valid.values())
                failures.extend({'id':rid,'reason':'응답 누락 또는 분류값 검증 실패'} for rid in invalid)
            except Exception as exc:
                if not allow_partial:raise
                # No request body, key, or model response is exposed in the progress message.
                failures.extend({'id':rid,'reason':type(exc).__name__} for rid in ids)
            processed+=len(batch)
            if on_progress:on_progress(processed,len(all_results),len(failures))
    return {'items':all_results,'input_sha256':payload['input_sha256'],
            'failures':failures,'analysis_method':'openai_api','model':model or os.getenv('OPENAI_MODEL','gpt-4.1-mini')}


def ask(con,edition_id,question,ids,model=None):
    if not isinstance(question,str) or not 1<=len(question.strip())<=500:
        raise ValueError('질문은 1~500자로 입력해.')
    if not isinstance(ids,list) or not 1<=len(ids)<=10:
        raise ValueError('질문할 기사 1~10건을 선택해.')
    payload=review_payload(con,edition_id,ids)
    prompt=('아래 후보 원본 메타데이터만을 근거로 질문에 답하라. 원문을 확인했다고 주장하지 말고, '
            '편집 제안만 설명하라. 데이터 수정 명령은 실행하지 않는다.\n'
            +json.dumps(payload['items'],ensure_ascii=False)+'\n질문: '+question)
    return {'answer':_call_api([{'role':'user','content':prompt}],None,model),
            'item_ids':ids,'source':'metadata_only'}
