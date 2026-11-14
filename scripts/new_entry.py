"""Create a public article without changing original Notion Markdown or CSV.

Example:
  python scripts/new_entry.py --group 'Темы' --title 'Этика' --slug etika \
      --body-file /tmp/etika.md --relation 'Личности=d5303c3cb5d8405b8915abd0d9074c9f'
"""
import argparse
import json
import re
import uuid
from pathlib import Path

from editorial_entries import GROUP_PREFIX, RELATION_FIELDS, SLUG, load_entries, relational_row
from audit_content import opening_paragraph, prose_chars

ROOT = Path(__file__).resolve().parents[1]


def create_entry(root, group, title, slug, body, relations=None, dry_run=False,
                 birth=None, death=None):
    root = Path(root)
    title = title.strip()
    if group not in GROUP_PREFIX or not title or len(title) > 180:
        raise ValueError('Choose a supported section and a nonempty title')
    if not SLUG.fullmatch(slug):
        raise ValueError('Slug must contain lowercase ASCII words separated by hyphens')
    if not 100 <= len(opening_paragraph(body)) <= 650:
        raise ValueError('First paragraph must explain the idea in 100–650 characters')
    if prose_chars(body) < 250:
        raise ValueError('Article is too short; add a complete, substantive description')
    if group in ('Темы', 'История философии') and not re.search(
            r'(?im)^#{2,4}\s*(источники|литература|библиография)', body):
        raise ValueError('Add a bibliography heading to a philosophical topic or period')

    entries = load_entries(root)
    data = root / 'content' / 'editorial' / 'entries.json'
    slugs_path = root / 'content' / 'slugs.json'
    registry = json.loads(data.read_text(encoding='utf-8'))
    slugs = json.loads(slugs_path.read_text(encoding='utf-8'))
    original = root / 'content' / 'notion'
    if any(p.is_file() and p.read_text(encoding='utf-8').splitlines()[0].strip() == '# ' + title
           and p.parent.name == group for p in original.rglob('*.md')):
        raise ValueError('Article with this title already exists in Notion export')
    if any(e['group'] == group and e['title'].casefold() == title.casefold() for e in entries):
        raise ValueError('Article with this title already exists in editorial registry')
    canonical = GROUP_PREFIX[group] + '/' + slug + '/'
    if canonical in slugs.values():
        raise ValueError('Canonical slug already exists')

    relations = relations or {}
    if set(relations) - RELATION_FIELDS[group]:
        raise ValueError('Unsupported relation field for this entry')
    for field, targets in relations.items():
        if not targets or len(set(targets)) != len(targets):
            raise ValueError('Duplicate or empty explicit relation list: ' + field)
        if any(pid not in slugs for pid in targets):
            raise ValueError('Relations must point to published stable IDs: ' + field)

    pid = uuid.uuid4().hex
    props = ''
    if group == 'Личности':
        if not birth or not str(birth).strip():
            raise ValueError('For a philosopher specify the birth year')
        props = 'Год рождения: ' + str(birth).strip() + '\n'
        if death:
            props += 'Год смерти: ' + str(death).strip() + '\n'
    markdown = '# ' + title + '\n\n' + props + ('\n' if props else '') + body.strip() + '\n'
    record = {'id':pid,'title':title,'group':group,'slug':slug,'relations':relations}
    if dry_run:
        return {'id':pid, 'url':canonical, 'path':None, 'dry_run':True}
    path = root / 'content' / 'editorial' / 'pages' / (pid + '.md')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding='utf-8')
    try:
        registry['entries'].append(record)
        slugs[pid] = canonical
        data.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        slugs_path.write_text(json.dumps(dict(sorted(slugs.items())), ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')
        load_entries(root)  # Verify post-write schema.
    except Exception:
        # A failed operation must not leave an incomplete editorial record.
        path.unlink(missing_ok=True)
        registry['entries'].remove(record)
        data.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        slugs.pop(pid, None)
        slugs_path.write_text(json.dumps(dict(sorted(slugs.items())), ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')
        raise
    return {'id':pid,'url':canonical,'path':str(path),'dry_run':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Repository root')
    parser.add_argument('--group', choices=tuple(GROUP_PREFIX), required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--slug', required=True)
    parser.add_argument('--body-file', type=Path, required=True)
    parser.add_argument('--birth', help='Birth year for biographies (negative for BCE)')
    parser.add_argument('--death', help='Death year for biographies, when applicable')
    parser.add_argument('--relation', action='append', default=[], metavar='FIELD=ID',
                        help='Repeat for multiple relationships; only existing public IDs')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    relations = {}
    for raw in args.relation:
        if '=' not in raw:
            parser.error('Relations must have FIELD=ID format')
        key, pid = raw.split('=', 1)
        relations.setdefault(key, []).append(pid)
    result = create_entry(args.root,args.group,args.title,args.slug,
                          args.body_file.read_text(encoding='utf-8'),
                          relations,dry_run=args.dry_run,
                          birth=args.birth,death=args.death)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
