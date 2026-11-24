"""Portable user files, separate from bundled assets and the database."""
import hashlib
import os
import re
import tempfile
from pathlib import Path

def safe_stem(value):
    name=str(value or '').replace('\\','/').rsplit('/',1)[-1]
    name=re.sub(r'[^\w.-]+','_',name,flags=re.UNICODE).strip(' ._')
    return name[:40].rstrip(' .') or 'file'

def edition_folder(edition_id):
    return safe_stem(edition_id)+'-'+hashlib.sha256(str(edition_id).encode()).hexdigest()[:8]

def workspace_for_db(db_path):
    parent=Path(db_path).resolve().parent
    return parent.parent if parent.name.lower()=='data' else parent

class ManagedFiles:
    def __init__(self,workspace):
        self.root=Path(workspace).resolve()/'files'
        for path in ('branding/defaults','branding/custom','imports','exports'):
            self.directory(path)
    def directory(self,relative):
        path=self.root/relative
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Managed folder outside workspace')
        path.mkdir(parents=True,exist_ok=True)
        return path
    def save(self,relative,name,content,extension):
        if not isinstance(content,bytes):raise TypeError('Managed file must be bytes')
        if extension not in ('.jpg','.png','.csv','.json','.html'):
            raise ValueError('Unsupported managed file type')
        folder=self.directory(relative)
        stem=safe_stem(Path(str(name or 'file').replace('\\','/')).stem)
        digest=hashlib.sha256(content).hexdigest()[:20]
        path=folder/(stem+'-'+digest+extension)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Managed file outside workspace')
        if path.exists():
            if path.read_bytes()!=content:raise OSError('Managed file hash collision')
        else:
            fd,tmp=tempfile.mkstemp(prefix='.write-',dir=folder)
            try:
                with os.fdopen(fd,'wb') as f:f.write(content)
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        return str(path.relative_to(self.root)).replace('\\','/')
    def import_file(self,eid,category,name,content,extension):
        return self.save('imports/'+edition_folder(eid)+'/'+category,name,content,extension)
    def export_file(self,eid,category,name,content,extension):
        if isinstance(content,str):content=content.encode('utf8')
        return self.save('exports/'+edition_folder(eid)+'/'+category,name,content,extension)
    def brand_image(self,role,image):
        import base64
        if role not in ('logo','banner','footer'):raise ValueError('Invalid image role')
        mime,encoded=image.split(',',1)
        extension='.png' if mime=='data:image/png;base64' else '.jpg'
        return self.save('branding/custom/'+role,role,base64.b64decode(encoded,validate=True),extension)
    def info(self):
        return {'root':str(self.root),'branding':'branding','imports':'imports','exports':'exports',
                'can_open':os.name=='nt'}
