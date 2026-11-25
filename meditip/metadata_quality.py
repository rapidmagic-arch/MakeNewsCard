"""Source metadata quality, separate from editorial decisions."""
import re

def title_needs_review(row):
    r=dict(row)
    title=r.get('title') or ''
    if r.get('verification')=='needs_title_review' or not title.strip() or len(title)>190:
        return True
    if r.get('source_key') in ('yakup','dailypharm') and re.match(r'^\d{1,2}\s+\S',title):
        # Legacy ranking prefixes are ambiguous: flag for explicit recheck, never strip digits.
        import json
        try:meta=json.loads(r.get('original_metadata') or '{}')
        except (ValueError,TypeError):meta={}
        if not isinstance(meta,dict) or meta.get('title_extraction') not in ('dedicated_headline','dedicated_detail_headline'):
            return True
    if r.get('source_key')=='medicaltimes':
        return bool(re.search(r'\[\s*메디칼타임즈\s*=|\[제목 확인 필요\]|20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}',title))
    return False
