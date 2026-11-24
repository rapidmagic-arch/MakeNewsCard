"""Local newsletter branding; no external image requests or invented contacts."""
import base64
import binascii
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

FIELDS={'contact_name':80,'phone':80,'email':254,'address':300,'website':500}
IMAGES=('logo','banner','footer')
# Original user-provided issue 892 (2026-11-17), sample defaults, not independently current.
SAMPLE_CONTACT={'contact_name':'최서영','phone':'070-7733-0340','email':'sychoi@meditip.co.kr',
                'address':'서울특별시 강남구 개포로 619, 10층 (개포동, 서울강남우체국빌딩) 우.06336',
                'website':'http://meditip.co.kr/'}

def get_default_contact(con):
    row=con.execute("SELECT value FROM newsletter_branding WHERE key='default_contact'").fetchone()
    return json.loads(row['value']) if row else dict(SAMPLE_CONTACT)

def validated_contact(obj):
    data={}
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
    return data

def save_default_contact(con,obj):
    data=validated_contact(obj)
    # Keep the current effective publishing contact even before its first explicit save.
    current=get_branding(con)
    con.execute("INSERT OR IGNORE INTO newsletter_branding VALUES('branding',?)",(json.dumps(current,ensure_ascii=False),))
    con.execute("INSERT INTO newsletter_branding VALUES('default_contact',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(data,ensure_ascii=False),))
    con.commit()
    return data

def get_branding(con):
    row=con.execute("SELECT value FROM newsletter_branding WHERE key='branding'").fetchone()
    return json.loads(row['value']) if row else get_default_contact(con)

def public_branding(con):
    data=get_branding(con)
    return {**{key:data.get(key,'') for key in FIELDS},
            **{key+'_custom':bool(data.get(key)) for key in IMAGES},'sample_contact':dict(SAMPLE_CONTACT),'default_contact':get_default_contact(con)}

def save_branding(con,obj,managed=None):
    data=get_branding(con)
    data.update(validated_contact(obj))
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
    if managed:
        for key in IMAGES:
            if data.get(key):managed.brand_image(key,data[key])
    con.execute("INSERT INTO newsletter_branding VALUES('branding',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(data,ensure_ascii=False),))
    con.commit()
    return public_branding(con)

def default_banner(template_path):
    return bundled_image(template_path,'meditip-banner-hd.jpg') or bundled_image(template_path,'meditip-mvp-banner.jpg')

def default_footer(template_path):
    return bundled_image(template_path,'meditip-footer-hd.jpg')

def bundled_image(template_path,name):
    path=Path(template_path).resolve().parent.parent/'assets'/'newsletter'/name
    return 'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode('ascii') if path.is_file() else ''

def contact_lines(data):
    result=[]
    if data.get('address'):result.append(data['address'])
    line=' · '.join(data[k] for k in ('contact_name','phone','email') if data.get(k))
    if line:result.append(line)
    if data.get('website'):result.append(data['website'])
    return result
