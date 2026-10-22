"""Self-contained local reference; no remote scripts, fetch, or editor calls."""
import json
from pathlib import Path


def render(data, path):
    template = Path(__file__).with_name('template.html').read_text(encoding='utf-8')
    from .discovery import Discovery
    # Only the browser needs membership lists; the DS first-layer index stays small.
    data = dict(data)
    discovery = Discovery(Path(path).parent / 'discovery')
    data['discovery'] = {**discovery.index, 'clusters': [
        {**c, 'nodeKeys': [n['key'] for n in discovery.read(f'clusters/{c["id"]}.json')['nodes']]}
        for c in discovery.index['clusters']]}
    # Source strings remain JSON data, never HTML markup or executable script.
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    Path(path).write_text(template.replace('/*__CATALOG__*/', payload), encoding='utf-8')
