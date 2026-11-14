"""Public editorial additions live beside, never inside, the immutable Notion export.

Stable IDs, approved slug prefixes and explicit typed IDs are required. Data
validation runs in the generator and editorial auditor before publication.
"""
import json
import re
from pathlib import Path

GROUP_PREFIX = {'Темы':'topics', 'Личности':'people',
                'История философии':'history'}
RELATION_FIELDS = {
    'Темы': {'История философии', 'Личности', 'Связь'},
    'Личности': {'Темы', 'История философии'},
    'История философии': {'Темы', 'Личности'},
}
PID = re.compile(r'[0-9a-f]{32}')
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def load_entries(root):
    """Validate and return complete public additions, without mutating sources."""
    root = Path(root)
    registry = root / 'content' / 'editorial' / 'entries.json'
    source = json.loads(registry.read_text(encoding='utf-8'))
    if source.get('version') != 1 or not isinstance(source.get('entries'), list):
        raise ValueError('Unsupported editorial entry registry')
    known_ids, known_slugs, known_titles = set(), set(), set()
    result = []
    base = root / 'content' / 'editorial' / 'pages'
    for item in source['entries']:
        if not isinstance(item, dict):
            raise ValueError('Invalid editorial entry')
        pid, title, group, slug = (item.get(k) for k in ('id','title','group','slug'))
        if not isinstance(pid, str) or not PID.fullmatch(pid):
            raise ValueError('Editorial entry ID must be lowercase UUID hex')
        if not isinstance(title, str) or not 3 <= len(title.strip()) <= 180 or title != title.strip():
            raise ValueError('Invalid editorial entry title')
        if group not in GROUP_PREFIX:
            raise ValueError('Unsupported editorial group')
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError('Editorial slug must be lowercase ASCII words separated by hyphens')
        if pid in known_ids or (group, title.casefold()) in known_titles or (group, slug) in known_slugs:
            raise ValueError('Duplicate editorial ID, title or slug')
        known_ids.add(pid)
        known_titles.add((group, title.casefold()))
        known_slugs.add((group, slug))
        path = base / (pid + '.md')
        if not path.is_file():
            raise ValueError('Missing editorial Markdown: ' + pid)
        text = path.read_text(encoding='utf-8')
        if not text.startswith('# ' + title + '\n'):
            raise ValueError('Editorial title and Markdown heading differ: ' + pid)
        relations = item.get('relations', {})
        if not isinstance(relations, dict) or set(relations) - RELATION_FIELDS[group]:
            raise ValueError('Invalid editorial relation field: ' + pid)
        for field, targets in relations.items():
            if not isinstance(targets, list) or not targets or any(
                not isinstance(target, str) or not PID.fullmatch(target) or target == pid
                for target in targets
            ) or len(set(targets)) != len(targets):
                raise ValueError('Invalid editorial relation IDs: ' + pid + ':' + field)
        result.append({'id': pid, 'title': title, 'group': group,
                       'slug': GROUP_PREFIX[group] + '/' + slug + '/',
                       'path': path, 'text': text, 'relations': relations})
    return result


def relational_row(entry, pages):
    """Adapt stable ID relations to the legacy CSV row interface."""
    row = {'Name': entry['title']}
    # Editorial biography facts are carried in the Markdown front matter,
    # rather than modifying Notion's exported CSV tables.
    for line in entry['text'].splitlines()[1:]:
        value = line.strip()
        if not value:
            continue
        if not value.startswith(('Год рождения: ', 'Год смерти: ')):
            break
        key, text = value.split(': ', 1)
        if key in {'Год рождения', 'Год смерти'}:
            row[key] = text
    for field, targets in entry['relations'].items():
        for pid in targets:
            if pid not in pages or pages[pid]['group'] not in GROUP_PREFIX:
                raise ValueError('Editorial link targets an unknown or non-public entity: ' + pid)
        row[field] = ', '.join(pages[pid]['title'] + ' (' + pid + '.md)' for pid in targets)
    return row
