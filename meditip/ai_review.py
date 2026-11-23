"""One review engine for HTTP and CLI. No API call without explicit user action.

The raw source remains untouched. Responses are proposals, never publishing actions.
"""
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
    raw=json.dumps(items,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return {'schema_version':'meditip-ai-candidate-1','edition_id':edition_id,
            'input_sha256':hashlib.sha256(raw.encode('utf8')).hexdigest(),'items':items,
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


def analyze(payload,model=None):
    """Analyze up to 20 candidate metadata records per independent request."""
    if not payload['items']:return {'items':[]}
    all_results=[]
    for index in range(0,len(payload['items']),20):
        batch=payload['items'][index:index+20]
        instruction=('한국어 제약·바이오 뉴스레터 편집 보조다. 메타데이터만 제공하므로 제목에서 확인되지 않은 사실을 생성하지 마. '
                     '분야와 관련성을 보수적으로 판정하고 입력의 source_group에 맞는 section만 사용해. 추천 이유·요약은 검증 전 제안으로 작성해. '
                     '입력의 각 id에 대해 정확히 하나씩 JSON 결과를 반환하고 미확인 사항은 reason에 명시해.')
        output=json.loads(_call_api([{'role':'system','content':instruction},
                                     {'role':'user','content':json.dumps(batch,ensure_ascii=False)}],SCHEMA,model))
        if not isinstance(output,dict) or not isinstance(output.get('items'),list):raise ValueError('Invalid AI response schema')
        ids=[x['id'] for x in batch]
        results=output['items']
        if len(results)!=len(ids) or set(x.get('id') for x in results)!=set(ids):
            raise ValueError('AI returned missing, duplicated or foreign item IDs')
        for result in results:
            if (not isinstance(result.get('section'),str) or result['section'] not in
                    SCHEMA['properties']['items']['items']['properties']['section']['enum']
                    or result.get('relevance') not in ('relevant','irrelevant','review_needed')
                    or not isinstance(result.get('recommended'),bool)
                    or not isinstance(result.get('score'),(int,float))
                    or not 0 <= result['score'] <= 100
                    or not isinstance(result.get('reason'),str)
                    or not isinstance(result.get('summary'),str)):
                raise ValueError('Invalid AI classification data')
        all_results.extend(results)
    return {'items':all_results,'input_sha256':payload['input_sha256'],
            'analysis_method':'openai_api','model':model or os.getenv('OPENAI_MODEL','gpt-4.1-mini')}


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
