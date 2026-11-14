"""Standalone curated entries: append-only overlay, never edit the Notion export."""
import json
import re
from pathlib import Path

KINDS = {'Темы': 'topics', 'Личности': 'people', 'История философии': 'history'}
ID = re.compile(r'^[a-f0-9]{32}$')
SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def editorial_paths(root):
    base = Path(root) / 'content' / 'editorial'
    return base / 'entries.json', base / 'articles'


def load_entries(root, include_drafts=False):
    manifest, articles = editorial_paths(root)
    if not manifest.exists():
        return []
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    if payload.get('version') != 1 or not isinstance(payload.get('entries'), list):
        raise ValueError('Invalid editorial manifest version or entries')
    seen_ids, seen_slugs, entries = set(), set(), []
    for entry in payload['entries']:
        pid = entry.get('id', '')
        kind = entry.get('group')
        slug = entry.get('slug', '')
        title = entry.get('title', '').strip()
        status = entry.get('status')
        relations = entry.get('relations', [])
        if not ID.fullmatch(pid) or pid in seen_ids:
            raise ValueError('Invalid/duplicate editorial ID: ' + str(pid))
        if kind not in KINDS or not SLUG.fullmatch(slug):
            raise ValueError('Invalid editorial group or slug: ' + str(title))
        url = KINDS[kind] + '/' + slug + '/'
        if url in seen_slugs:
            raise ValueError('Duplicate editorial slug: ' + url)
        if not title or len(title) > 150 or status not in ('draft', 'published'):
            raise ValueError('Invalid editorial title/status: ' + str(pid))
        if not isinstance(relations, list) or any(
            not isinstance(item, str) or not ID.fullmatch(item)
            for item in relations
        ) or len(set(relations)) != len(relations) or pid in relations:
            raise ValueError('Invalid editorial relations: ' + str(pid))
        path = articles / (pid + '.md')
        if not path.is_file():
            raise ValueError('Missing editorial Markdown: ' + str(path))
        content = path.read_text(encoding='utf-8')
        if not content.startswith('# ' + title + '\n'):
            raise ValueError('Editorial title differs from Markdown heading: ' + str(pid))
        seen_ids.add(pid)
        seen_slugs.add(url)
        if include_drafts or status == 'published':
            entries.append({**entry, 'path': path, 'text': content, 'url': url})
    return entries


def relation_fields(entry, pages):
    """Reproduce the exported CSV link convention without touching CSV."""
    row = {'Name': entry['title']}
    for pid in entry['relations']:
        if pid not in pages or pages[pid]['group'] not in KINDS:
            raise ValueError('Editorial relation to non-public/unknown ID: ' + pid)
        group = pages[pid]['group']
        key = group if group != entry['group'] else 'Связь'
        value = pages[pid]['title'] + ' (' + pid + '.md)'
        row[key] = ', '.join(filter(None, (row.get(key, ''), value)))
    return row
