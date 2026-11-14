"""Export a public, evidence-preserving graph from the original Notion relations.

No claim of influence, agreement, disagreement, or philosophical causality is
inferred from a CSV relationship. Original Notion IDs and public slugs remain
the canonical identifiers. Private/homework records are never exposed.
"""
import re
from urllib.parse import unquote

RELATION_COLUMNS = {
    'Темы': ('История философии', 'Личности', 'Связь'),
    'История философии': ('Темы', 'Личности'),
    'Личности': ('Темы', 'История философии'),
}
ID_REFERENCE = re.compile(r'([a-f0-9]{32})\.md')


def build_graph(pages, rows_by_id, ordered, slugs):
    """Return deterministic nodes and undirected edges with CSV provenance."""
    ids = set(slugs)
    nodes = [{
        'id': p['id'],
        'title': p['title'],
        'group': p['group'],
        'url': slugs[p['id']],
    } for group in ('Темы', 'История философии', 'Личности')
        for p in ordered[group] if p['id'] in ids]
    nodes.sort(key=lambda n: (n['group'], n['title'].casefold(), n['id']))
    if {n['id'] for n in nodes} != ids:
        raise ValueError('Graph nodes must exactly match canonical published slugs')

    edges = {}
    for node in nodes:
        source = node['id']
        row = rows_by_id[source]
        for column in RELATION_COLUMNS[node['group']]:
            value = unquote(row.get(column, ''))
            for target in sorted(set(ID_REFERENCE.findall(value))):
                if target not in ids or target == source:
                    continue
                key = tuple(sorted((source, target)))
                evidence = {'from': source, 'field': column}
                entry = edges.setdefault(key, {
                    'source': key[0], 'target': key[1],
                    'type': 'explicit_relation', 'evidence': [],
                })
                if evidence not in entry['evidence']:
                    entry['evidence'].append(evidence)
    for edge in edges.values():
        edge['evidence'].sort(key=lambda e: (e['from'], e['field']))
    result = {
        'version': 1,
        'nodes': nodes,
        'edges': sorted(edges.values(), key=lambda e: (e['source'], e['target'])),
    }
    if any(e['source'] not in ids or e['target'] not in ids or not e['evidence']
           for e in result['edges']):
        raise ValueError('Graph contains an invalid or unsupported public connection')
    return result
