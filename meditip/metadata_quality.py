"""Source metadata quality, separate from editorial decisions."""
import re

def title_needs_review(row):
    r=dict(row)
    title=r.get('title') or ''
    if r.get('verification')=='needs_title_review' or not title.strip() or len(title)>190:
        return True
    if r.get('source_key')=='medicaltimes':
        return bool(re.search(r'\[\s*메디칼타임즈\s*=|\[제목 확인 필요\]|20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}',title))
    return False
