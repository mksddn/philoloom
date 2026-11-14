"""Regression tests for the source-preserving content inventory."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_content import audit, opening_paragraph, page_parts, prose_chars


A = 'a' * 32
B = 'b' * 32
C = 'c' * 32
D = 'd' * 32


class EditorialAuditTests(unittest.TestCase):
    def test_initial_heading_is_not_an_intro(self):
        self.assertEqual(opening_paragraph('## Заголовок\n\nПотом идёт объяснение.'), '')
        self.assertEqual(opening_paragraph('[Внешняя ссылка](https://example.org)'), '')
        self.assertTrue(opening_paragraph('Понятие — объяснение.'))
        self.assertTrue(opening_paragraph('**Русский космизм** — направление.'))
        self.assertTrue(opening_paragraph('*Гуманизм* — историческая традиция.'))
        self.assertEqual(opening_paragraph('* Пункт списка'), '')
        self.assertEqual(opening_paragraph('- Пункт списка'), '')
        self.assertEqual(opening_paragraph('1. Первый пункт'), '')
        self.assertEqual(opening_paragraph('![Портрет](portrait.jpg)'), '')

    def test_public_corpus_has_no_empty_or_unsourced_articles(self):
        """Final corpus-level checks: all published long-form records have text and citations."""
        result = audit()
        public = [r for r in result['entries'] if r['scope'] == 'public']
        self.assertEqual(len(public), 124)
        self.assertEqual(result['summary']['by_status'], {'needs-review': 124})
        for row in public:
            with self.subTest(title=row['title'], section=row['section']):
                self.assertNotIn('empty_body', row['findings'])
                self.assertNotIn('stub_review', row['findings'])
                self.assertNotIn('duplicate_title_review', row['findings'])
                self.assertNotIn('missing_public_slug', row['findings'])
                self.assertNotIn('broken_internal_references', row['findings'])
                if row['section'] in ('Темы', 'История философии'):
                    self.assertNotIn('sources_review', row['findings'])
                if row['section'] == 'Темы':
                    self.assertNotIn('missing_intro', row['findings'])
                    self.assertNotIn('intro_length_review', row['findings'])
                if row['section'] == 'Личности':
                    self.assertGreaterEqual(row['body_chars'], 250)
        self.assertFalse(result['possible_duplicates'])
        self.assertFalse(result['csv_warnings'])
        self.assertFalse(result['invalid_filenames'])
        self.assertFalse(result['duplicate_ids'])
        self.assertFalse(any(row['scope'] == 'public' and row['unresolved_links']
                             for row in result['entries']))
        self.assertEqual(sum('isolated_review' in e['findings'] for e in public), 0)

    def test_property_stripping_matches_site_builder(self):
        props, body = page_parts('# Тема\n\nЛичности: Текст\nГод: 2026\n\nВступление.\n')
        self.assertEqual(list(props), ['Личности', 'Год'])
        self.assertEqual(body, 'Вступление.')
        self.assertEqual(prose_chars('[Только внешняя ссылка](https://example.org)'), 0)

    def test_full_inventory_csv_backlinks_and_exclusions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notion = root / 'content' / 'notion' / 'Философия'
            for group in ('Темы', 'Личности', 'Цитаты', 'Самостоятельная работа'):
                (notion / group).mkdir(parents=True)
            (notion / 'Темы' / f'Тема {A}.md').write_text(
                '# Разум\n\n## Начало\n\nТекст.\n', encoding='utf-8')
            (notion / 'Темы' / f'Тема2 {B}.md').write_text(
                '# Разум\n\nРазум — философское понятие.\n\n'
                'Содержательное обсуждение. ' * 20, encoding='utf-8')
            (notion / 'Личности' / f'Личность {C}.md').write_text(
                '# Мыслитель\n\nГод рождения: 1800\nГод смерти: 1870\n\n'
                'Содержательный текст философа. ' * 12, encoding='utf-8')
            (notion / 'Самостоятельная работа' / f'Личное {D}.md').write_text(
                '# Мои заметки\n\nНе публично', encoding='utf-8')
            (notion / f'Темы {"f"*32}_all.csv').write_text(
                'Name,Личности\n'
                f'Разум,Мыслитель ({C}.md)\n'
                f'Разум,Мыслитель ({C}.md)\n', encoding='utf-8')
            (root / 'content' / 'slugs.json').write_text(json.dumps({
                A: 'topics/razum/', B: 'topics/razum-2/',
                C: 'people/myslitel/'}), encoding='utf-8')
            report = audit(root)
            self.assertEqual(report['pages'], 4)
            self.assertEqual(report['summary']['public'], 3)
            self.assertEqual(report['summary']['excluded'], 1)
            self.assertEqual(len(report['possible_duplicates']), 1)
            self.assertFalse(report['unresolved_references'])
            topic = next(x for x in report['entries'] if x['id'] == A)
            thinker = next(x for x in report['entries'] if x['id'] == C)
            homework = next(x for x in report['entries'] if x['id'] == D)
            self.assertIn('missing_intro', topic['findings'])
            self.assertEqual(topic['direct_links'], 1)
            self.assertEqual(thinker['incoming_links'], 2)
            self.assertEqual(homework['status'], 'excluded')
            self.assertIsNone(homework['public_url'])


if __name__ == '__main__':
    unittest.main()