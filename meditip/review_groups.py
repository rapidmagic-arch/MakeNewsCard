"""User-managed recommendation keyword groups; newsletter output sections remain fixed."""
import json
from uuid import uuid4

SECTIONS = ('industry.policy', 'industry.market', 'industry.global', 'industry.rnd')
LABELS = {'industry.policy':'정책', 'industry.market':'시장',
          'industry.global':'글로벌', 'industry.rnd':'연구개발'}


def init_groups(con, defaults):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS review_groups (
      id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, target_section TEXT NOT NULL,
      keywords_json TEXT NOT NULL, recommend INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS config_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    if not con.execute("SELECT 1 FROM config_meta WHERE key='review_groups_seeded'").fetchone():
        for section in SECTIONS:
            terms=(defaults or {}).get(section,[])
            con.execute('''INSERT OR IGNORE INTO review_groups(id,label,target_section,keywords_json,recommend)
                           VALUES(?,?,?,?,1)''',
                        ('default-'+section.split('.')[-1],LABELS[section],section,
                         json.dumps(list(terms),ensure_ascii=False)))
        con.execute("INSERT INTO config_meta VALUES('review_groups_seeded','1')")
        con.commit()


def list_groups(con):
    return [{'id':r['id'],'label':r['label'],'target_section':r['target_section'],
             'keywords':json.loads(r['keywords_json']),'recommend':bool(r['recommend'])}
            for r in con.execute('SELECT * FROM review_groups ORDER BY created_at,id')]


def save_group(con, data):
    if not isinstance(data,dict):raise ValueError('그룹 입력을 확인해.')
    label=data.get('label');section=data.get('target_section');keywords=data.get('keywords');recommend=data.get('recommend')
    if not isinstance(label,str) or not 1<=len(label.strip())<=40:raise ValueError('그룹명은 1~40자로 입력해.')
    label=label.strip()
    if section not in SECTIONS:raise ValueError('출력 분야는 정책·시장·글로벌·연구개발 중에서 선택해.')
    if not isinstance(keywords,list) or not 1<=len(keywords)<=30 or not all(isinstance(k,str) for k in keywords):
        raise ValueError('키워드는 1~30개 입력해.')
    norm=list(dict.fromkeys(k.strip() for k in keywords if k.strip()))
    if not norm or any(len(k)>60 for k in norm):raise ValueError('빈 키워드 또는 60자 초과 키워드를 확인해.')
    if not isinstance(recommend,bool):raise ValueError('수록 추천 여부를 지정해.')
    group_id=data.get('id')
    if group_id is not None and (not isinstance(group_id,str) or not con.execute('SELECT 1 FROM review_groups WHERE id=?',(group_id,)).fetchone()):
        raise ValueError('변경 대상 그룹이 없어.')
    if con.execute('SELECT 1 FROM review_groups WHERE label=? AND id<>?',(label,group_id or '')).fetchone():
        raise ValueError('같은 이름의 그룹이 이미 있어.')
    group_id=group_id or 'custom-'+uuid4().hex[:16]
    con.execute('''INSERT INTO review_groups(id,label,target_section,keywords_json,recommend)
                   VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,
                   target_section=excluded.target_section,keywords_json=excluded.keywords_json,
                   recommend=excluded.recommend''',
                (group_id,label,section,json.dumps(norm,ensure_ascii=False),int(recommend)))
    con.commit()
    return group_id


def delete_group(con,group_id):
    if not isinstance(group_id,str):raise ValueError('그룹 ID가 올바르지 않아.')
    deleted=con.execute('DELETE FROM review_groups WHERE id=?',(group_id,)).rowcount
    if deleted!=1:raise ValueError('삭제할 그룹이 없어.')
    con.commit()


def with_groups(con,editorial):
    return {**(editorial or {}),'review_groups':list_groups(con)}
