"""A typed philosophical relationship must be grounded in a source and locator."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.semantic_links import load_semantic_links

A, B = 'a' * 32, 'b' * 32


class SemanticLinksTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'content/editorial/semantic-links.json'
        self.path.parent.mkdir(parents=True)

    def save(self, links):
        self.path.write_text(json.dumps({'version': 1, 'links': links}), encoding='utf-8')

    def test_empty_editorial_registry_makes_no_philosophical_claims(self):
        self.save([])
        self.assertEqual(load_semantic_links(self.root, {A, B}), [])

    def test_sourced_link_has_direction_and_precise_locator(self):
        link = {'source': A, 'target': B, 'relation': 'criticizes',
                'evidence': {'work': 'Гипотетическая проверяемая работа',
                             'locator': 'Глава 2, § 4',
                             'url': 'https://example.org/source'}}
        self.save([link])
        self.assertEqual(load_semantic_links(self.root, {A, B}), [link])
        self.save([link, link])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_semantic_links(self.root, {A, B})

    def test_reject_unknown_targets_and_unsupported_sources(self):
        sample = {'source': A, 'target': B, 'relation': 'develops',
                  'evidence': {'work': 'Книга о философии', 'locator': '§3'}}
        for invalid in (
            {**sample, 'target': 'c' * 32},
            {**sample, 'source': B, 'target': B},
            {**sample, 'relation': 'invented_relation'},
            {**sample, 'evidence': {'work': 'Текст', 'locator': ''}},
            {**sample, 'evidence': {**sample['evidence'], 'url': 'javascript:alert(1)'}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.save([invalid])
                load_semantic_links(self.root, {A, B})


if __name__ == '__main__':
    unittest.main()
