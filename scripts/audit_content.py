"""Reproducible, non-destructive editorial inventory of the Notion export.

Heuristics identify review candidates; they never certify philosophical accuracy.
Run from any directory. Reports cover all exported Markdown, but only the four
published sections are eligible for public editorial prioritization.
"""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / 'content' / 'notion'
PUBLIC_GROUPS = {'Темы', 'Личности', 'История философии', 'Цитаты'}
STABLE_ID = re.compile(r'([a-f0-9]{32})\.md$', re.I)
REFERENCED_ID = re.compile(r'([a-f0-9]{32})\.md', re.I)
PROPERTY = re.compile(r'^[^#>\-*\[\n]{1,35}: ')
PLACEHOLDERS = {'тема', 'личность', 'цитата', 'название работы', 'направление'}
SOLO_LINK = re.compile(r'^\[[^]]+\]\([^)]*\)$')


def page_parts(text):
    """Mirror the builder's initial property parsing without editing source."""
    lines = text.splitlines()[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    properties = {}
    while lines and PROPERTY.match(lines[0]):
        key, value = lines.pop(0).split(': ', 1)
        properties[key] = value
    return properties, '\n'.join(lines).strip()


def substantive_body(lines):
    """Backwards-compatible helper: strip heading and exported properties."""
    return page_parts('\n'.join(lines))[1]


def opening_paragraph(body):
    """The *first* visible block must be prose (not prose after a heading)."""
    blocks = re.split(r'\n\s*\n', body.strip()) if body.strip() else []
    first = blocks[0].strip() if blocks else ''
    if (not first or first.startswith(('#', '!', '|', '-', '*', '>', chr(96) * 3, '<'))
            or SOLO_LINK.fullmatch(first)):
        return ''
    return re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', first).strip()


def prose_chars(body):
    """Exclude decorations, headings and standalone bookmarks from word count."""
    lines, fenced = [], False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(chr(96) * 3):
            fenced = not fenced
            continue
        if fenced or not s or s.startswith(('#', '![', '<img', '|', '---')):
            continue
        if SOLO_LINK.fullmatch(s):
            continue
        line = re.sub(r'!\[[^]]*\]\([^)]*\)', '', line)
        line = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', line)
        line = re.sub(r'<[^>]+>', '', line)
        line = re.sub(r'(?<!\w)[*_\x60>]+', '', line)
        lines.append(line)
    return len(re.sub(r'\s+', ' ', ' '.join(lines)).strip())


def refs(text):
    return set(m.lower() for m in REFERENCED_ID.findall(unquote(text)))


def load_csv_metadata(content, records):
    """Match _all.csv rows to stable IDs in export order, like build.py."""
    by_group_title = defaultdict(list)
    for record in records.values():
        by_group_title[(record['section'], record['title'])].append(record['id'])
    assigned = defaultdict(int)
    csv_rows, warnings = {}, []
    for path in sorted(content.rglob('*_all.csv')):
        group = re.sub(r' [a-f0-9]{32}_all$', '', path.stem, flags=re.I)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            key = (group, row.get('Name', ''))
            n = assigned[key]
            available = by_group_title[key]
            if n >= len(available):
                warnings.append({'csv': path.relative_to(content).as_posix(),
                                 'title': row.get('Name', ''), 'issue': 'csv_row_unmatched'})
                continue
            csv_rows[available[n]] = row
            assigned[key] += 1
    return csv_rows, warnings


def audit(root=ROOT):
    root = Path(root)
    content = root / 'content' / 'notion'
    slugs_file = root / 'content' / 'slugs.json'
    slugs = json.loads(slugs_file.read_text(encoding='utf-8')) if slugs_file.exists() else {}
    records, invalid_names, duplicate_ids = {}, [], []
    titles = defaultdict(list)
    for path in sorted(content.rglob('*.md')):
        rel = path.relative_to(root).as_posix()
        match = STABLE_ID.search(path.name)
        if not match:
            invalid_names.append(rel)
            continue
        pid = match[1].lower()
        if pid in records:
            duplicate_ids.append({'id': pid, 'paths': [records[pid]['path'], rel]})
            continue
        text = path.read_text(encoding='utf-8')
        title = (text.splitlines()[0].removeprefix('# ').strip() if text.splitlines() else '')
        section = path.parent.name if path.parent != content else '(root)'
        props, body = page_parts(text)
        published = section in PUBLIC_GROUPS
        row = dict(id=pid, title=title, section=section, path=rel,
                   scope='public' if published else 'excluded',
                   public_url=None, body_chars=prose_chars(body),
                   intro_chars=len(opening_paragraph(body)),
                   properties=props, _body=body, _source=text,
                   markdown_refs=refs(text) - {pid})
        records[pid] = row
        titles[(section, ' '.join(title.casefold().split()))].append(pid)

    csv_rows, csv_warnings = load_csv_metadata(content, records)
    graph_out = {pid: set() for pid in records}
    graph_in = {pid: set() for pid in records}
    unresolved = []
    for pid, row in records.items():
        csv_refs = refs(' '.join(str(v) for k, v in csv_rows.get(pid, {}).items()
                                 if k not in ('Name', 'Конспект', 'Задание')))
        target_ids = (row['markdown_refs'] | csv_refs) - {pid}
        for target in target_ids:
            if target in records:
                graph_out[pid].add(target)
                graph_in[target].add(pid)
            else:
                unresolved.append({'source_id': pid, 'source': row['path'], 'target_id': target})
        row['csv_refs'] = csv_refs - {pid}

    duplicate_titles = [
        {'section': section, 'title': records[ids[0]]['title'],
         'paths': [records[i]['path'] for i in ids], 'ids': ids}
        for (section, title), ids in sorted(titles.items()) if title and len(ids) > 1
    ]
    duplicated = {pid for item in duplicate_titles for pid in item['ids']}
    broken_by_id = Counter(x['source_id'] for x in unresolved)
    home_url = 'https://mksddn.github.io/philoloom/'
    entries, placeholders = [], []
    for pid, row in records.items():
        section, title, body = row['section'], row['title'], row['_body']
        if section in PUBLIC_GROUPS and section != 'Цитаты':
            row['public_url'] = home_url + slugs[pid] if pid in slugs else None
        elif section == 'Цитаты':
            row['public_url'] = home_url + '#quote-' + pid
        findings = []
        if not title or title.casefold() in PLACEHOLDERS:
            findings.append('placeholder')
            placeholders.append({'section': section, 'title': title or '(empty)', 'path': row['path']})
        if section in PUBLIC_GROUPS and section != 'Цитаты':
            if row['body_chars'] == 0:
                findings.append('empty_body')
            elif row['body_chars'] < 250:
                findings.append('stub_review')
        if section == 'Темы':
            intro = opening_paragraph(body)
            if not intro:
                findings.append('missing_intro')
            elif not 100 <= len(intro) <= 650:
                findings.append('intro_length_review')
        if pid in duplicated:
            findings.append('duplicate_title_review')
        if broken_by_id[pid]:
            findings.append('broken_internal_references')
        if section in PUBLIC_GROUPS and section != 'Цитаты' and not row['public_url']:
            findings.append('missing_public_slug')
        if section in PUBLIC_GROUPS and not graph_out[pid] and not graph_in[pid]:
            findings.append('isolated_review')
        # These flags are review prompts, not judgments of truth or attribution.
        if section == 'Цитаты':
            findings.append('quotation_source_review')
        elif section == 'Личности':
            if not row['properties'].get('Год рождения') or not row['properties'].get('Год смерти'):
                findings.append('biographical_dates_review')
        elif section in ('Темы', 'История философии') and not re.search(
                r'(?im)^#{2,4}\s*(источники|литература|библиография)', body):
            findings.append('sources_review')

        # Human review, not heuristic length, is the only path to "ready".
        if row['scope'] == 'excluded':
            status, priority = 'excluded', None
        elif 'placeholder' in findings or 'empty_body' in findings:
            status, priority = 'empty', 1
        elif 'stub_review' in findings or 'missing_intro' in findings:
            status, priority = 'stub', 2
        else:
            status = 'needs-review'
            priority = 1 if ('duplicate_title_review' in findings or
                             'broken_internal_references' in findings or
                             'missing_public_slug' in findings) else 3
        entries.append({
            'section': section, 'title': title, 'id': pid, 'path': row['path'],
            'scope': row['scope'], 'public_url': row['public_url'],
            'body_chars': row['body_chars'], 'intro_chars': row['intro_chars'],
            'explicit_internal_refs': len(row['markdown_refs']),
            'csv_internal_refs': len(row['csv_refs']),
            'direct_links': len(graph_out[pid]), 'incoming_links': len(graph_in[pid]),
            'unresolved_links': broken_by_id[pid],
            'status': status, 'priority': priority, 'findings': sorted(set(findings)),
        })

    entries.sort(key=lambda e: (e['priority'] if e['priority'] is not None else 9,
                                e['section'], e['title'].casefold(), e['id']))
    publish = [e for e in entries if e['scope'] == 'public']
    return {
        'pages': len(entries),
        'summary': {
            'public': len(publish), 'excluded': len(entries) - len(publish),
            'by_section': dict(sorted(Counter(e['section'] for e in entries).items())),
            'by_status': dict(sorted(Counter(e['status'] for e in publish).items())),
            'by_priority': dict(sorted(Counter(str(e['priority']) for e in publish).items())),
            'finding_counts': dict(sorted(Counter(f for e in publish for f in e['findings']).items())),
        },
        'possible_duplicates': duplicate_titles,
        'possible_placeholders': placeholders,
        'invalid_filenames': invalid_names,
        'duplicate_ids': duplicate_ids,
        'csv_warnings': csv_warnings,
        'unresolved_references': sorted(unresolved, key=lambda a: (a['source'], a['target_id'])),
        'entries': entries,
        'note': ('Heuristic inventory: "ready" requires independent editorial verification. '
                 'Unpublished homework is excluded; quotations require source verification. '
                 'CSV relations are paired in export order; outgoing links are not inferred '
                 'from incoming links. No files are modified.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Write JSON report to this path')
    parser.add_argument('--root', type=Path, default=ROOT, help='Repository root (for fixtures)')
    parser.add_argument('--summary', action='store_true', help='Print concise aggregate results')
    parser.add_argument('--strict', action='store_true', help='Fail on structural anomalies (opt-in)')
    args = parser.parse_args()
    result = audit(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['summary'] if args.summary else result, ensure_ascii=False, indent=2))
    if args.strict and any(result[k] for k in (
            'possible_duplicates', 'possible_placeholders', 'invalid_filenames',
            'duplicate_ids', 'csv_warnings', 'unresolved_references')):
        raise SystemExit(1)


if __name__ == '__main__':
    main()