"""Evidence-checked directional philosophical relations, separate from mere mentions.

Every relation is an editorial claim and needs a source and a precise locator.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

KINDS = {
    'develops': 'развивает идеи',
    'criticizes': 'критикует',
    'influences': 'оказал влияние на',
    'belongs_to': 'относится к',
    'responds_to': 'полемизирует с',
}


def load_semantic_links(root, valid_ids):
    path = Path(root) / 'content' / 'editorial' / 'semantic-links.json'
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('links'), list):
        raise ValueError('Invalid semantic links manifest')
    seen = set()
    for link in data['links']:
        source, target, kind = (link.get(key) for key in ('source', 'target', 'relation'))
        evidence = link.get('evidence')
        if source not in valid_ids or target not in valid_ids or source == target:
            raise ValueError('Semantic link references an invalid/non-public ID')
        if kind not in KINDS or (source, target, kind) in seen:
            raise ValueError('Invalid/duplicate relation type')
        if not isinstance(evidence, dict):
            raise ValueError('Semantic link requires source evidence')
        work = evidence.get('work', '').strip()
        locator = evidence.get('locator', '').strip()
        url = evidence.get('url', '').strip()
        if len(work) < 5 or len(locator) < 2:
            raise ValueError('Semantic links require a work and precise locator')
        if url:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError('Semantic source URL must be HTTPS')
        seen.add((source, target, kind))
    return data['links']
