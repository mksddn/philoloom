"""Create and publish original Philoloom articles without changing Notion exports.

Examples:
  python scripts/content.py create --group Темы --title "Название" --slug nazvanie --related <ID>
  python scripts/content.py publish <ID>
  python scripts/content.py list
"""
import argparse
import json
import uuid
from pathlib import Path

from editorial_entries import ID, KINDS, SLUG, editorial_paths, load_entries
from audit_content import opening_paragraph, page_parts, prose_chars

ROOT = Path(__file__).resolve().parents[1]


def save_manifest(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Project root (for tests)')
    commands = parser.add_subparsers(dest='action', required=True)
    create = commands.add_parser('create', help='Create an unpublished original article')
    create.add_argument('--group', choices=KINDS, required=True)
    create.add_argument('--title', required=True)
    create.add_argument('--slug', required=True, help='Lowercase Latin URL segment')
    create.add_argument('--related', action='append', default=[], metavar='ID',
                        help='Existing published record ID; may be repeated')
    publish = commands.add_parser('publish', help='Publish after editorial checks')
    publish.add_argument('id', help='Stable 32-digit ID')
    commands.add_parser('list', help='Show original editorial additions and statuses')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest, articles = editorial_paths(root)
    payload = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {
        'version': 1, 'entries': []
    }
    # Fail on corrupt manifests rather than accidentally overwriting them.
    existing = load_entries(root, include_drafts=True)
    if args.action == 'list':
        for entry in existing:
            print(entry['status'], entry['id'], entry['group'], entry['title'], entry['url'])
        return
    if args.action == 'create':
        title = args.title.strip()
        slug = args.slug.strip()
        if not title or len(title) > 150 or not SLUG.fullmatch(slug):
            parser.error('A nonempty title and an ASCII lowercase hyphenated slug are required')
        if len(set(args.related)) != len(args.related) or any(
            not ID.fullmatch(ref) for ref in args.related
        ):
            parser.error('Related IDs must be unique 32-digit lowercase hexadecimal values')
        url = KINDS[args.group] + '/' + slug + '/'
        canonical = json.loads((root / 'content/slugs.json').read_text(encoding='utf-8'))
        if url in canonical.values() or any(entry['url'] == url for entry in existing):
            parser.error('This canonical URL already belongs to another record')
        if any(entry['group'] == args.group and entry['title'].casefold() == title.casefold()
               for entry in existing):
            parser.error('An original article with this title already exists')
        available = set(canonical) | {entry['id'] for entry in existing
                                       if entry['status'] == 'published'}
        if any(ref not in available for ref in args.related):
            parser.error('Each related ID must already be published')
        pid = uuid.uuid4().hex
        while pid in available or any(entry['id'] == pid for entry in existing):
            pid = uuid.uuid4().hex
        articles.mkdir(parents=True, exist_ok=True)
        path = articles / (pid + '.md')
        content = ('# ' + title + '\n\n'
                   'TODO: Раскройте центральную мысль через понятный пример или философский вопрос.\n\n'
                   '## Основные положения\n\n'
                   'TODO: Добавьте самостоятельное объяснение и возражения.\n\n'
                   '## Источники и дальнейшее чтение\n\n'
                   'TODO: Укажите проверяемые первоисточники или академические работы.\n')
        path.write_text(content, encoding='utf-8')
        payload['entries'].append({'id': pid, 'group': args.group, 'title': title,
                                   'slug': slug, 'status': 'draft',
                                   'relations': args.related})
        save_manifest(manifest, payload)
        print('Created draft:', pid, path.relative_to(root))
        return
    record = next((entry for entry in existing if entry['id'] == args.id), None)
    if record is None:
        parser.error('Unknown editorial article ID')
    if record['status'] == 'published':
        print('Already published:', record['id'])
        return
    _, body = page_parts(record['text'])
    intro = opening_paragraph(body)
    errors = []
    if 'TODO' in body:
        errors.append('replace all TODO placeholders')
    if not 100 <= len(intro) <= 650:
        errors.append('write a content-first first paragraph of 100–650 characters')
    if prose_chars(body) < 250:
        errors.append('write at least 250 characters of substantive prose')
    if record['group'] in ('Темы', 'История философии') and not any(
        heading in body.lower() for heading in
        ('## источники', '## литература', '## библиография')
    ):
        errors.append('add a bibliography section')
    if not record['relations']:
        errors.append('add at least one verified related record in entries.json')
    if errors:
        parser.error('Publication requirements: ' + '; '.join(errors))
    for item in payload['entries']:
        if item['id'] == record['id']:
            item['status'] = 'published'
    save_manifest(manifest, payload)
    print('Published:', record['id'], record['url'])


if __name__ == '__main__':
    main()
