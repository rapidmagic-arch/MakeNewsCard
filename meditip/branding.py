"""Local newsletter branding; no external image requests or invented contacts."""
import base64
import binascii
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

FIELDS={'contact_name':80,'phone':80,'email':254,'address':300,'website':500}
IMAGES=('logo','banner')

def get_branding(con):
    row=con.execute("SELECT value FROM newsletter_branding WHERE key='branding'").fetchone()
    return json.loads(row['value']) if row else {}

def public_branding(con):
    data=get_branding(con)
    return {**{key:data.get(key,'') for key in FIELDS},
            **{key+'_custom':bool(data.get(key)) for key in IMAGES}}

def save_branding(con,obj):
    data=get_branding(con)
    for key,limit in FIELDS.items():
        value=obj.get(key,'')
        if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 for c in value):
            raise ValueError('Invalid branding field: '+key)
        data[key]=value.strip()
    if data['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',data['email']):
        raise ValueError('Invalid contact email')
    if data['website']:
        url=urlsplit(data['website'])
        if url.scheme not in ('https','http') or not url.hostname or url.username or url.password:
            raise ValueError('Invalid website URL')
    for key in IMAGES:
        image=obj.get(key)
        if image is None:continue
        if image=='':data.pop(key,None);continue
        if not isinstance(image,str) or not image.startswith(('data:image/jpeg;base64,','data:image/png;base64,')):
            raise ValueError('Only JPEG or PNG images are accepted')
        mime,encoded=image.split(',',1)
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error):raise ValueError('Invalid image data')
        if not raw or len(raw)>1_000_000:raise ValueError('Image limit: 1MB each')
        if mime=='data:image/jpeg;base64':
            if not raw.startswith(b'\xff\xd8\xff') or not raw.endswith(b'\xff\xd9'):raise ValueError('Invalid JPEG')
        elif not raw.startswith(b'\x89PNG\r\n\x1a\n') or raw[12:16]!=b'IHDR':
            raise ValueError('Invalid PNG')
        data[key]=image
    con.execute("INSERT INTO newsletter_branding VALUES('branding',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(data,ensure_ascii=False),))
    con.commit()
    return public_branding(con)

def default_banner(template_path):
    path=Path(template_path).resolve().parent.parent/'assets'/'newsletter'/'meditip-mvp-banner.jpg'
    return 'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode('ascii') if path.is_file() else ''

def contact_lines(data):
    result=[]
    if data.get('address'):result.append(data['address'])
    line=' · '.join(data[k] for k in ('contact_name','phone','email') if data.get(k))
    if line:result.append(line)
    if data.get('website'):result.append(data['website'])
    return result
