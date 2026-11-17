"""Knowledge map is explicit-link only, stable, and progressive."""
import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_graph import create_graph


class KnowledgeMapTests(unittest.TestCase):
    def test_graph_is_only_public_records(self):
        data = create_graph()
        slugs = json.loads((ROOT / 'content' / 'slugs.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['nodes']), 113)
        self.assertEqual({n['id'] for n in data['nodes']}, set(slugs))
        self.assertEqual({n['url'] for n in data['nodes']}, set(slugs.values()))
        self.assertEqual({n['type'] for n in data['nodes']}, {'topic', 'person', 'history'})
        self.assertEqual(len(data['edges']), len({(e['source'], e['target'], e['provenance'], e['relation']) for e in data['edges']}))
        ids = set(slugs)
        self.assertTrue(data['edges'])
        for edge in data['edges']:
            self.assertIn(edge['source'], ids)
            self.assertIn(edge['target'], ids)
            self.assertNotEqual(edge['source'], edge['target'])
            self.assertIn(edge['provenance'], ('field', 'article'))

    def test_graph_is_reproducible(self):
        self.assertEqual(create_graph(), create_graph())

    def test_map_outputs_and_accessible_directory(self):
        out = ROOT / 'dist'
        data = json.loads((out / 'knowledge-map.json').read_text(encoding='utf-8'))
        self.assertEqual(data, create_graph())
        self.assertTrue((out / 'knowledge-map.js').exists())
        self.assertTrue((out / 'knowledge-map.css').exists())
        html = (out / 'map' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="map-visual"', html)
        self.assertIn('id="map-neighbor-list"', html)
        self.assertIn('aria-label="Карта связей"', html)
        for record in data['nodes']:
            self.assertIn('href="' + record['url'] + '"', html)
        home = (out / 'index.html').read_text(encoding='utf-8')
        self.assertIn('href="map/"', home)


if __name__ == '__main__':
    unittest.main()
