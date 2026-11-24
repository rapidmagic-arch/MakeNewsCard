"""Compose the editor for offline browser tests; runtime serves static JS separately."""
from pathlib import Path

SCRIPT_TAG='<script src="/assets/editor.js"></script>'

def read_editor(path, inline_script=False):
    path=Path(path)
    html=path.read_text(encoding='utf8')
    if not inline_script:return html
    if html.count(SCRIPT_TAG)!=1:raise ValueError('Missing or duplicate editor script tag')
    script=(path.parent/'assets'/'editor.js').read_text(encoding='utf8')
    return html.replace(SCRIPT_TAG,'<script>'+script+'</script>')
