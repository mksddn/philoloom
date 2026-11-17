"""Build a transparent, source-derived map from public Notion IDs and explicit links.

No philosophical relation (influence, criticism, school membership) is inferred.
All paths and IDs come from the published slug register, Markdown and CSV export.
"""
import csv
import html
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r'([a-f0-9]{32})\.md')
TYPES = {'Темы': 'topic', 'Личности': 'person', 'История философии': 'history'}


def create_graph(root=ROOT):
    source = root / 'content' / 'notion'
    slugs = json.loads((root / 'content' / 'slugs.json').read_text(encoding='utf-8'))
    nodes = {}
    document_paths = {}
    for path in sorted(source.rglob('*.md')):
        found = re.search(r'([a-f0-9]{32})(?:_all)?\.md$', path.name)
        if not found or found[1] not in slugs:
            continue
        identifier = found[1]
        if identifier in nodes:
            raise ValueError(f'Duplicate public entity ID: {identifier}')
        if path.parent.name not in TYPES:
            raise ValueError(f'Unexpected public content type: {path}')
        document = path.read_text(encoding='utf-8')
        nodes[identifier] = {
            'id': identifier, 'label': document.splitlines()[0].removeprefix('# ').strip(),
            'type': TYPES[path.parent.name], 'url': slugs[identifier]
        }
        document_paths[identifier] = path

    if set(nodes) != set(slugs):
        raise ValueError('Knowledge map differs from canonical public slug registry')

    edges = set()
    rejected = []
    # CSV properties are explicit statements in the Notion database. Their
    # direction is merely "the source record links to the target record".
    for path in sorted(source.rglob('*_all.csv')):
        group = re.sub(r' [a-f0-9]{32}_all$', '', path.stem)
        if group not in TYPES:
            continue
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        records_by_title = {}
        for identifier, node in nodes.items():
            if node['type'] == TYPES[group]:
                records_by_title.setdefault(node['label'], []).append(identifier)
        used = Counter()
        for row in rows:
            title = row.get('Name', '')
            matches = records_by_title.get(title, ())
            position = used[title]
            used[title] += 1
            if position >= len(matches):
                # Removed template or nonpublic archive row.
                continue
            source_id = matches[position]
            for key, value in row.items():
                if key in ('Name', 'Конспект', 'Моя работа', 'Задание', 'Зачтено') or not value:
                    continue
                for target_id in ID.findall(__import__('urllib.parse', fromlist=['unquote']).unquote(value)):
                    if target_id in nodes and target_id != source_id:
                        edges.add((source_id, target_id, 'field', key))
                    elif target_id not in nodes:
                        rejected.append({'source': source_id, 'target': target_id, 'field': key})

    # A Markdown link to another public article is also explicit. Do not
    # turn plain-text name matches into knowledge-graph relationships.
    from urllib.parse import unquote
    for identifier, path in document_paths.items():
        text = unquote(path.read_text(encoding='utf-8'))
        for target_id in ID.findall(text):
            if target_id in nodes and target_id != identifier:
                edges.add((identifier, target_id, 'article', 'Ссылка из статьи'))

    output = {
        'schema_version': 1,
        'policy': 'Only explicit public Markdown links and Notion CSV relations; no inferred influence.',
        'nodes': sorted(nodes.values(), key=lambda node: (node['type'], node['label'].casefold(), node['id'])),
        'edges': [
            {'source': a, 'target': b, 'provenance': origin, 'relation': label}
            for a, b, origin, label in sorted(edges)
        ]
    }
    valid = set(nodes)
    for edge in output['edges']:
        if edge['source'] not in valid or edge['target'] not in valid:
            raise ValueError('Nonpublic target in knowledge map')
    return output


def write_map(root=ROOT, out=None):
    target = out or root / 'dist'
    target.mkdir(parents=True, exist_ok=True)
    graph = create_graph(root)
    (target / 'knowledge-map.json').write_text(
        json.dumps(graph, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    for name in ('knowledge-map.js', 'knowledge-map.css'):
        (target / name).write_bytes((root / 'site' / name).read_bytes())
    groups = [
        ('topic', 'Темы'), ('history', 'История философии'), ('person', 'Личности')
    ]
    catalogs = []
    for kind, label in groups:
        entries = [node for node in graph['nodes'] if node['type'] == kind]
        links = ''.join(
            '<li><a href="../' + html.escape(node['url'], quote=True) + '">'
            + html.escape(node['label']) + '</a></li>' for node in entries)
        catalogs.append('<details class="map-directory"><summary>' + label + ' (' +
                        str(len(entries)) + ')</summary><ul>' + links + '</ul></details>')

    page = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="description" content="Исследуйте подтверждённые явными ссылками связи между философскими темами, мыслителями и эпохами.">
<title>Карта философских знаний · philoloom</title>
<base href="../"><link rel="canonical" href="https://mksddn.github.io/philoloom/map/">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="stylesheet" href="style.css"><link rel="stylesheet" href="knowledge-map.css">
<script src="knowledge-map.js" defer></script></head>
<body><a class="skip" href="#main">К содержимому</a><main id="main" class="map-page">
<div class="map-container"><nav class="map-back" aria-label="Навигация"><a href="index.html">← К справочнику</a></nav>
<header class="map-heading"><p class="map-kicker">philoloom · исследование связей</p>
<h1>Карта философских знаний</h1>
<p>Выберите понятие, эпоху или мыслителя, чтобы увидеть связи с другими записями.
На карте показаны только явные ссылки из исходных материалов: близость узлов не доказывает философского влияния.</p></header>
<div class="map-controls"><label for="map-search">Найти сущность<input id="map-search" type="search"
placeholder="Например, онтология или Кант" autocomplete="off"></label>
<label for="map-type">Тип сущности<select id="map-type">
<option value="all">Все</option><option value="topic">Темы</option>
<option value="person">Личности</option><option value="history">История</option></select></label></div>
<div class="map-layout"><section class="map-visual-panel" aria-label="Карта связей">
<div class="map-focus"><p id="map-current" aria-live="polite">Выберите запись</p>
<a id="map-open" href="index.html">Открыть статью</a></div>
<svg id="map-visual" role="img" aria-label="Соседние записи выбранной сущности" viewBox="0 0 900 550">
<text x="450" y="275" text-anchor="middle">Загрузка карты…</text></svg>
<p class="map-disclaimer">Линия означает прямую ссылку между записями, не причинное влияние.
Клик по соседнему узлу переключает выбранную запись.</p></section>
<aside class="map-neighbors"><h2>Связанные записи <span id="map-count"></span></h2>
<ul id="map-neighbor-list"><li>Выберите запись из списка ниже</li></ul></aside></div>
<section class="map-directory-section" aria-labelledby="directory-title">
<h2 id="directory-title">Все записи</h2>
<p>Доступны также без JavaScript. Ссылки ведут на канонические страницы.</p>
""" + '\n'.join(catalogs) + """
</section></div></main><footer><div class="map-container">
<a href="index.html">philoloom</a> · Интерактивная карта философских знаний
</div></footer></body></html>"""
    directory = target / 'map'
    directory.mkdir(exist_ok=True)
    (directory / 'index.html').write_text(page, encoding='utf-8')
    return graph


if __name__ == '__main__':
    graph = write_map()
    print(f"Knowledge map: {len(graph['nodes'])} nodes, {len(graph['edges'])} explicit links")
