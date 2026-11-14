"""Curated-article pipeline must keep the original Notion export immutable."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.content import main
from scripts.editorial_entries import load_entries


class ContentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old_id = 'f' * 32
        (self.root / 'content/notion').mkdir(parents=True)
        (self.root / 'content/slugs.json').write_text(
            json.dumps({self.old_id: 'topics/staraya-tema/'}), encoding='utf-8')
        self.original = self.root / 'content/notion/original.md'
        self.original.write_text('Исходный экспорт Notion — не изменять.\n', encoding='utf-8')

    def test_create_and_publish_new_article_without_editing_notions_sources(self):
        before = self.original.read_bytes()
        main(['--root', str(self.root), 'create', '--group', 'Темы',
              '--title', 'Новая идея', '--slug', 'novaya-ideya',
              '--related', self.old_id])
        manifest = self.root / 'content/editorial/entries.json'
        draft = json.loads(manifest.read_text())['entries'][0]
        pid = draft['id']
        self.assertEqual(draft['status'], 'draft')
        self.assertEqual(load_entries(self.root), [])
        self.assertEqual(len(load_entries(self.root, include_drafts=True)), 1)
        with self.assertRaises(SystemExit):
            main(['--root', str(self.root), 'publish', pid])
        self.assertEqual(draft['status'], 'draft')
        text = ('# Новая идея\n\n'
                'Когда люди пытаются объяснить поступки, они сопоставляют собственные '
                'убеждения и возможные последствия. Почему одинаковые доводы иногда '
                'приводят нас к разным решениям? Это вопрос о способах рассуждения '
                'и ответственности человека.\n\n'
                '## Основные положения\n\n'
                'В одном случае довод опирается на правило, действующее для всех, '
                'а в другом — на ожидаемые последствия конкретного поступка. '
                'Нельзя автоматически считать одинаковые выводы одинаково обоснованными.\n\n'
                '## Источники и дальнейшее чтение\n\n'
                'Пример библиографического раздела для редакционной проверки.\n')
        (self.root / 'content/editorial/articles' / (pid + '.md')).write_text(
            text, encoding='utf-8')
        main(['--root', str(self.root), 'publish', pid])
        public = load_entries(self.root)
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]['url'], 'topics/novaya-ideya/')
        self.assertEqual(public[0]['relations'], [self.old_id])
        self.assertEqual(before, self.original.read_bytes())

    def test_reject_duplicate_or_unsafe_slugs(self):
        for slug in ('staraya-tema', '../escape', 'Русское название'):
            with self.subTest(slug=slug):
                with self.assertRaises(SystemExit):
                    main(['--root', str(self.root), 'create', '--group', 'Темы',
                          '--title', 'Новая идея', '--slug', slug])


if __name__ == '__main__':
    unittest.main()
