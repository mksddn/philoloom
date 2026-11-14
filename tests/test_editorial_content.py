"""Compatibility and safety tests for supplementary authoring and canonical URLs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from editorial_entries import load_entries, relational_row
from new_entry import create_entry
from site_config import canonical_base, custom_domain, configured_site_url, DEFAULT_SITE_URL


class NewEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        editorial = self.root / 'content' / 'editorial'
        editorial.mkdir(parents=True)
        (editorial / 'entries.json').write_text(json.dumps({'version': 1, 'entries': []}), encoding='utf-8')
        self.related = 'a' * 32
        (self.root / 'content' / 'slugs.json').write_text(
            json.dumps({self.related: 'people/author/'}), encoding='utf-8')
        (self.root / 'content' / 'notion').mkdir()
        self.body = (
            'Почему человек должен отвечать за свои действия, если на решение влияют '
            'общество, привычки и воспитание? Философы обсуждают, на каких условиях '
            'поступок можно считать свободным и что делает моральную оценку обоснованной.\n\n'
            'Этот вопрос касается опыта повседневной жизни и способа обсуждать '
            'ответственность. Одни авторы связывают её с намерением и долгом, '
            'другие — с последствиями выбора и отношениями между людьми.\n\n'
            '## Источники и дальнейшее чтение\n\n'
            '- Конкретную библиографию редактор проверяет до публикации.'
        )

    def test_new_topic_and_evidence_references_are_separate_from_notion(self):
        result = create_entry(self.root, 'Темы', 'Ответственность',
                              'otvetstvennost', self.body, {'Личности': [self.related]})
        self.assertEqual(result['url'], 'topics/otvetstvennost/')
        self.assertTrue(Path(result['path']).is_file())
        entry = load_entries(self.root)[0]
        self.assertEqual(entry['id'], result['id'])
        self.assertIn(self.related + '.md',
                      relational_row(entry, {self.related: {'title': 'Автор', 'group': 'Личности'}})['Личности'])
        slugs = json.loads((self.root / 'content' / 'slugs.json').read_text())
        self.assertEqual(slugs[result['id']], result['url'])
        self.assertEqual(list((self.root / 'content' / 'notion').rglob('*')), [])

    def test_biography_dates_are_available_without_csv_changes(self):
        result = create_entry(self.root, 'Личности', 'Новый мыслитель',
                              'novyi-myslitel', self.body, birth='1777', death='1845')
        row = relational_row(load_entries(self.root)[0], {})
        self.assertEqual(row['Год рождения'], '1777')
        self.assertEqual(row['Год смерти'], '1845')
        self.assertIn('Год рождения: 1777', Path(result['path']).read_text())

    def test_dry_run_and_bad_metadata_do_not_touch_files(self):
        result = create_entry(self.root, 'Темы', 'Ответственность',
                              'otvetstvennost', self.body, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(load_entries(self.root), [])
        for invalid in ('../escape', 'space here', 'UPPERCASE'):
            with self.subTest(slug=invalid), self.assertRaises(ValueError):
                create_entry(self.root, 'Темы', 'Ответственность', invalid, self.body)
        with self.assertRaises(ValueError):
            create_entry(self.root, 'Темы', 'Ответственность', 'otvetstvennost',
                         self.body, {'Личности': ['b'*32]})
        self.assertEqual(load_entries(self.root), [])


class SiteURLTests(unittest.TestCase):
    def test_site_configuration(self):
        self.assertEqual(canonical_base(DEFAULT_SITE_URL), DEFAULT_SITE_URL)
        self.assertIsNone(custom_domain(DEFAULT_SITE_URL))
        self.assertEqual(canonical_base('https://philoloom.ru'), 'https://philoloom.ru/')
        self.assertEqual(custom_domain('https://philoloom.ru/'), 'philoloom.ru')
        with patch.dict('os.environ', {'PHILOLOOM_SITE_URL':'https://philoloom.ru/'}, clear=False):
            self.assertEqual(configured_site_url(), 'https://philoloom.ru/')

    def test_invalid_urls_are_rejected(self):
        for url in ('http://philoloom.ru','https://philoloom.ru/?utm=1',
                    'https://philoloom.ru/#fragment','https://philoloom.ru/../foo',
                    'https://bad:secret@example.org','javascript:alert(1)'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_base(url)


if __name__ == '__main__':
    unittest.main()
