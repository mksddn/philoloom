"""Regression checks for public Notion CSV and Markdown identity metadata.

These are consistency tests, not a substitute for scholarly source verification.
"""
import csv
import re
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / 'content' / 'notion'
PUBLIC = ('Темы', 'История философии', 'Личности', 'Цитаты')


def records(group):
    files = sorted(path for path in CONTENT.rglob('*.md') if path.parent.name == group)
    by_title = defaultdict(list)
    for path in files:
        text = path.read_text(encoding='utf-8')
        title = text.splitlines()[0].removeprefix('# ').strip()
        by_title[title].append((path, text))
    csv_paths = sorted(p for p in CONTENT.rglob('*_all.csv')
                       if re.sub(r' [a-f0-9]{32}_all$', '', p.stem) == group)
    if len(csv_paths) != 1:
        raise ValueError('Missing or ambiguous Notion CSV: ' + group)
    with csv_paths[0].open(encoding='utf-8-sig', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    used = defaultdict(int)
    result = []
    for row in csv_rows:
        title = row['Name']
        position = used[title]
        if position >= len(by_title[title]):
            raise ValueError('CSV record missing Markdown page: ' + title)
        used[title] += 1
        path, text = by_title[title][position]
        result.append((title, row, path, text))
    if sum(map(len, by_title.values())) != len(result):
        raise ValueError('Unmatched Markdown page in group ' + group)
    return result


class PublicContentConsistencyTests(unittest.TestCase):
    def test_every_public_csv_matches_a_markdown_heading(self):
        expected = {'Темы': 51, 'История философии': 9, 'Личности': 64, 'Цитаты': 11}
        for group, count in expected.items():
            with self.subTest(group=group):
                self.assertEqual(len(records(group)), count)

    def test_biographical_dates_agree_between_markdown_and_csv(self):
        for title, row, path, text in records('Личности'):
            for field in ('Год рождения', 'Год смерти'):
                with self.subTest(person=title, field=field):
                    match = re.search(r'^' + field + r':\s*(-?\d+)\s*$', text, re.MULTILINE)
                    markdown_value = match.group(1) if match else ''
                    csv_value = (row.get(field) or '').strip()
                    self.assertEqual(markdown_value, csv_value, str(path))

    def test_chinese_room_origin_and_historical_reciprocity(self):
        room = next(item for item in records('Темы') if item[0] == 'Китайская комната')
        self.assertIn('101b04bc57514b1cad67d7f6b207dcd9.md', room[1]['История философии'])
        self.assertIn('101b04bc57514b1cad67d7f6b207dcd9.md', room[3])
        history = {title: row for title, row, _, _ in records('История философии')}
        self.assertIn('b0221180ced546df90c4000ea04e5a3f.md',
                      history['Вторая половина ХХ века']['Темы'])
        self.assertNotIn('b0221180ced546df90c4000ea04e5a3f.md',
                         history['Философия XXI века']['Темы'])

    def test_anthropocentrism_and_correlationism_are_not_equated_by_csv(self):
        topic_rows = {title: row for title, row, _, _ in records('Темы')}
        self.assertNotIn('c2a6a8fa37144057aa2a2e308c479aa8.md',
                         str(topic_rows['Антропоцентризм']))
        self.assertNotIn('0bb5cd4cf7c348efaa07b4d077892b98.md',
                         str(topic_rows['Корреляционизм']))

    def test_corrected_philosopher_dates_and_quotes(self):
        people = {title: row for title, row, _, _ in records('Личности')}
        self.assertEqual(people['Джон Сёрл']['Год смерти'], '2025')
        self.assertEqual((people['Платон']['Год рождения'],
                          people['Платон']['Год смерти']), ('-427', '-347'))
        quote_titles = {title for title, _, _, _ in records('Цитаты')}
        self.assertIn('значение слова есть его употребление в речи', quote_titles)
        self.assertIn('Бытие, о котором для этого сущего идет дело в его бытии, всегда мое',
                      quote_titles)
        self.assertNotIn('Смысл слов зависит только от контекста', quote_titles)


if __name__ == '__main__':
    unittest.main()
