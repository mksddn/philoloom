"""Regression checks for public entity CSV and Markdown identity metadata.

These are consistency tests, not a substitute for scholarly source verification.
"""
import csv
import re
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / 'content' / 'knowledge'
PUBLIC = ('Темы', 'История философии', 'Личности', 'Цитаты')


def records(group):
    files = sorted(path for path in CONTENT.rglob('*.md') if path.parent.name == group)
    by_title = defaultdict(list)
    for path in files:
        text = path.read_text(encoding='utf-8')
        title = text.splitlines()[0].removeprefix('# ').strip()
        by_title[title].append((path, text))
    csv_paths = sorted(p for p in CONTENT.rglob('*_all.csv')
                       if p.stem.removesuffix('_all') == group)
    if len(csv_paths) != 1:
        raise ValueError('Missing or ambiguous entity CSV: ' + group)
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
        self.assertIn('history/vtoraya-polovina-hh-veka.md', room[1]['История философии'])
        self.assertIn('history/vtoraya-polovina-hh-veka.md', room[3])
        history = {title: row for title, row, _, _ in records('История философии')}
        self.assertIn('topics/kitaiskaya-komnata.md',
                      history['Вторая половина ХХ века']['Темы'])
        self.assertNotIn('topics/kitaiskaya-komnata.md',
                         history['Философия XXI века']['Темы'])

    def test_anthropocentrism_and_correlationism_are_not_equated_by_csv(self):
        topic_rows = {title: row for title, row, _, _ in records('Темы')}
        self.assertNotIn('topics/korrelyatsionizm.md',
                         str(topic_rows['Антропоцентризм']))
        self.assertNotIn('topics/antropotsentrizm.md',
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


    def test_relationships_match_markdown_properties_and_reciprocate(self):
        """Every typed public relation must exist in both exports and on both ends."""
        schema = {
            'Темы': {'Личности': ('Личности', 'Темы'),
                     'История философии': ('История философии', 'Темы'),
                     'Связь': ('Темы', 'Связь')},
            'Личности': {'Темы': ('Темы', 'Личности'),
                        'История философии': ('История философии', 'Личности')},
            'История философии': {'Темы': ('Темы', 'История философии'),
                                  'Личности': ('Личности', 'История философии')},
        }
        identity = {}
        for group in schema:
            for title, csv_row, path, source in records(group):
                match = re.search(r'([a-z0-9-]+)\.md$', path.name)
                self.assertIsNotNone(match, str(path))
                identity[{'Темы':'topics','Личности':'people','История философии':'history'}[group] + '/' + match.group(1)] = (group, title, csv_row, path, source)

        def referenced_ids(value):
            return set(re.findall(r'((?:people|topics|history|quotes|articles)/[a-z0-9-]+)\.md', value or '', re.I))

        def markdown_properties(source):
            properties = {}
            started = False
            for line in source.splitlines()[1:]:
                if not line.strip():
                    if started:
                        break
                    continue
                if line.startswith(('#', '![', '>', '-', '*', '[')):
                    break
                match = re.match(r'^([^:\n]{1,35}): (.*)$', line)
                if not match:
                    break
                properties[match.group(1)] = match.group(2)
                started = True
            return properties

        for source_id, (group, title, csv_row, path, source) in identity.items():
            props = markdown_properties(source)
            for field, (target_group, reverse_field) in schema[group].items():
                with self.subTest(group=group, title=title, field=field):
                    csv_targets = referenced_ids(csv_row.get(field))
                    markdown_targets = referenced_ids(props.get(field))
                    self.assertEqual(csv_targets, markdown_targets,
                                     'CSV/Markdown mismatch: ' + str(path))
                    for target_id in csv_targets:
                        self.assertIn(target_id, identity,
                                      'Unknown relation target from ' + title)
                        other_group, other_title, other_row, _, _ = identity[target_id]
                        self.assertEqual(other_group, target_group,
                                         'Wrong entity type in ' + title + ' -> ' + other_title)
                        self.assertIn(source_id,
                                      referenced_ids(other_row.get(reverse_field)),
                                      'Unreciprocated relation: ' + title + ' -> ' + other_title)


    def test_canonical_relationships_and_exclusions(self):
        """Editorially confirmed philosophy relations should survive later imports."""
        corpus = {
            group: {
                title: (row, {'Темы':'topics','Личности':'people','История философии':'history'}[group] + '/' + path.stem)
                for title, row, path, _ in records(group)
            }
            for group in ('Темы', 'Личности', 'История философии')
        }
        confirmed = (
            ('Неоплатонизм', 'История философии', 'Античная философия'),
            ('Патристика', 'Личности', 'Аврелий Августин'),
            ('Объектно-ориентированная онтология', 'Личности', 'Грэм Харман'),
            ('Эстетика', 'Личности', 'Иммануил Кант'),
            ('Государство', 'Личности', 'Платон'),
            ('Государство', 'Личности', 'Томас Гоббс'),
            ('Государство', 'Личности', 'Джон Локк'),
            ('Феноменология', 'Личности', 'Мартин Хайдеггер'),
            ('Онтология', 'Личности', 'Аристотель'),
        )
        for topic, target_group, target in confirmed:
            with self.subTest(topic=topic, related=target):
                row = corpus['Темы'][topic][0]
                target_id = corpus[target_group][target][1]
                self.assertIn(target_id + '.md', row.get(target_group, ''))

        rejected = (
            ('Структурализм', 'Жан-Поль Сартр'),
            ('Структурализм', 'Мишель Фуко'),
            ('Социология ассоциаций', 'Мишель Фуко'),
            ('Русский консерватизм', 'Николай Бердяев'),
            ('Экзистенциализм', 'Сёрен Обье Кьеркегор'),
            ('Экзистенциализм', 'Фридрих Ницше'),
        )
        for topic, thinker in rejected:
            with self.subTest(topic=topic, wrongly_attributed=thinker):
                row = corpus['Темы'][topic][0]
                person_id = corpus['Личности'][thinker][1]
                self.assertNotIn(person_id + '.md', row.get('Личности', ''))


if __name__ == '__main__':
    unittest.main()
