"""Integration checks for the generated reference and its image pipeline."""
import csv
import json
from html import unescape as html_unescape
import re
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from PIL import Image, ImageChops, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist'


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids, self.links = [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        for key in ('src', 'href', 'data-full-src'):
            if attrs.get(key):
                self.links.append(attrs[key])
        if attrs.get('srcset'):
            self.links.extend(item.strip().split()[0] for item in attrs['srcset'].split(','))


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / 'content/image-manifest.json').read_text())
        cls.slugs = json.loads((ROOT / 'content/slugs.json').read_text())

    def public_page(self, pid):
        return (OUT / self.slugs[pid] / 'index.html').read_text(encoding='utf-8')

    def test_all_pages_and_local_links_exist(self):
        entries = json.loads((OUT / 'search.json').read_text())
        self.assertEqual(len(entries), len(self.slugs) + 11)  # public pages + 11 inline quotes
        self.assertFalse(any(entry['url'] == 'index.html' for entry in entries),
                         'Homepage must not match every entity search query')
        self.assertEqual(sum(entry['group'] == 'Цитаты' for entry in entries), 11)
        self.assertFalse(any(entry['group'] == 'Самостоятельная работа' for entry in entries))
        for entry in entries:
            address = entry['url'].split('#', 1)[0]
            destination = OUT / address
            path = destination / 'index.html' if destination.is_dir() else destination
            self.assertTrue(path.is_file(), entry['title'])
            page = Page(path.read_text())
            self.assertEqual(len(page.ids), len(set(page.ids)), entry['title'])
            for link in page.links:
                parsed = urlsplit(link)
                if not parsed.scheme and parsed.path:
                    if parsed.path in ('../', '../../'):
                        continue
                    target = OUT / unquote(parsed.path)
                    if target.is_dir():
                        target = target / 'index.html'
                    self.assertTrue(target.is_file(), (entry['title'], link))

    def test_pinned_slugs_and_legacy_forwarding(self):
        self.assertEqual(self.slugs['c4c741fb50874c87a5d2cb4d4def5e50'], 'people/rene-dekart/')
        self.assertEqual(self.slugs['10ebde78a3c349b29057a45caee57a92'], 'topics/ontologiya/')
        self.assertEqual(len(set(self.slugs.values())), len(self.slugs))
        self.assertTrue(all((OUT / address / 'index.html').is_file() for address in self.slugs.values()))
        detail = self.public_page('c4c741fb50874c87a5d2cb4d4def5e50')
        self.assertIn('<base href="../../">', detail)
        self.assertIn('rel="canonical" href="https://mksddn.github.io/philoloom/people/rene-dekart/"', detail)
        legacy = (OUT / 'c4c741fb50874c87a5d2cb4d4def5e50.html').read_text()
        self.assertIn('name="robots" content="noindex,follow"', legacy)
        self.assertIn('url=people/rene-dekart/', legacy)
        sitemap = (OUT / 'sitemap.xml').read_text()
        self.assertIn('/people/rene-dekart/', sitemap)
        self.assertNotIn('c4c741fb50874c87a5d2cb4d4def5e50.html', sitemap)

    def test_slavophilism_merge_preserves_canonical_and_old_urls(self):
        canonical_id = '21618a276d8d80fd8c45c76380b480ba'
        retired_id = '21618a276d8d80b181ccf9d91811bd41'
        self.assertEqual(self.slugs[canonical_id], 'topics/slavyanofilstvo/')
        self.assertNotIn(retired_id, self.slugs)
        article = self.public_page(canonical_id)
        self.assertIn('Славянофильство', article)
        self.assertIn('Хомяков', article)
        for legacy in (retired_id + '.html', 'topics/slavyanofilstvo-21618a27/index.html'):
            page = (OUT / legacy).read_text(encoding='utf-8')
            self.assertIn('name="robots" content="noindex,follow"', page)
            self.assertIn('https://mksddn.github.io/philoloom/topics/slavyanofilstvo/', page)
        with next((ROOT / 'content/notion').rglob('Темы *_all.csv')).open(
                encoding='utf-8-sig', newline='') as stream:
            names = [row['Name'] for row in csv.DictReader(stream)]
        self.assertEqual(names.count('Славянофильство'), 1)
        search = json.loads((OUT / 'search.json').read_text(encoding='utf-8'))
        self.assertEqual(sum(x['title'] == 'Славянофильство' for x in search), 1)

    def test_foundational_philosophers_include_independent_content_and_sources(self):
        examples = {
            '5c62a805028a4272bd0b99d7e493d7bd': ('эленхос', 'Сократ'),
            '44efa008da2d4553911e0d6d29e3b795': ('эйдос', 'Платон'),
            'bed09a3399144396a503d79898e8a5ca': ('силлогизм', 'Аристотель'),
            'd5303c3cb5d8405b8915abd0d9074c9f': ('трансцендентальный', 'Иммануил Кант'),
        }
        for pid, (keyword, name) in examples.items():
            with self.subTest(philosopher=name):
                html = self.public_page(pid)
                self.assertIn(keyword, html.casefold())
                self.assertIn('Stanford Encyclopedia of Philosophy', html)
                self.assertIn('<article>', html)
                self.assertTrue(any(label in html for label in (
                    'Первоисточники', 'Основные сочинения', 'основные произведения')))

    def test_foundational_topics_have_clear_introductions(self):
        titles = {
            '2f72ef4fe8234fac95e4f7386c6828ff': 'Эллинизм',
            '680f3c6b79564cf7a4176bcd07c8f61b': 'Неоплатонизм',
            '6a3b16ed93cf45cfbe6c86b1c11bc000': 'Патристика',
            'a6f686e17d3149ac9b4ba3b31457a84e': 'Гуманизм',
            'c6def37927ee4cdb8cba31ceaebf68bd': 'Пифагорейская школа',
        }
        for pid, title in titles.items():
            with self.subTest(topic=title):
                page = self.public_page(pid)
                self.assertIn(title, page)
                self.assertIn('<article>', page)
                self.assertIn('Источники и исследования', page)

    def test_next_philosopher_batch_has_independent_explanations(self):
        """Eight philosopher cards have substantive text and retained metadata."""
        expected = {
            '6eda584ca34948838eae6bba482a1ea2': 'первичные качества',
            'ba21d53fa1ee428f9f0fdc01cde8ea14': 'индукции',
            '43d6e4e552094f21bd5e0de378f311fd': 'пограничных ситуаций',
            'f86d8811cb4446978333cb13528ee88e': 'идеология',
            'a6c8256c59de4bd0bdeb2f80bfa1e3cf': 'диалектика',
            '901b9cac4f5b412b9f1cd2084f255032': 'сверхчеловека',
            '10739540eb1a4ed594f8b542b7317867': 'бытие-в-мире',
            '3132d7f8d0844f899c62d7db011891b8': 'языковые игры',
        }
        for pid, term in expected.items():
            with self.subTest(pid=pid):
                article = self.public_page(pid)
                self.assertIn(term, article.casefold())
                self.assertIn('Основные произведения и исследования', article)
                self.assertIn('Год рождения', article)
                self.assertIn('entity-detail--people', article)
                self.assertIn('href="https://', article)

    def test_quotes_are_inline_and_deep_linkable(self):
        quote_id = '47d742c8761f4a0c86a27b43497759b0'
        home = (OUT / 'index.html').read_text()
        self.assertIn(f'id="quote-{quote_id}"', home)
        self.assertIn('class="quote-entry"', home)
        self.assertNotIn(f'href="{quote_id}.html"', home)
        legacy = (OUT / f'{quote_id}.html').read_text()
        self.assertIn(f'index.html#quote-{quote_id}', legacy)
        self.assertFalse((OUT / 'quotes').exists())
        descartes = self.public_page('c4c741fb50874c87a5d2cb4d4def5e50')
        self.assertIn('class="person-quotes"', descartes)


    def test_quotations_remain_clean_without_public_review_comments(self):
        """The reader sees the quotation and its author; provenance stays internal."""
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(home.count('class="quote-entry-label"'), 11)
        self.assertNotIn('class="quote-source-note"', home)
        self.assertNotIn('Точность русского перевода не сверена', home)
        self.assertNotIn('Возможный пересказ, не дословная цитата', home)
        self.assertIn('Если наказывать ребенка за дурное и награждать за доброе', home)
        descartes = self.public_page('c4c741fb50874c87a5d2cb4d4def5e50')
        self.assertNotIn('person-quote-note', descartes)
        self.assertNotIn('первоисточники цитат требуют проверки', descartes)

    def test_sections_remain_in_static_html(self):
        source = (OUT / 'index.html').read_text()
        self.assertEqual(source.count('class="reference-section"'), 5)
        self.assertNotIn('💪 Мои статьи', source)
        self.assertNotIn('data-view-content=', source)
        self.assertNotIn('class="view-controls"', source)
        self.assertIn('class="history-timeline"', source)
        self.assertIn('class="quote-catalog"', source)
        self.assertIn('id="more"', source)
        self.assertNotIn('class="reference-section" hidden', source)

    def test_catalog_cards_render_all_structured_links(self):
        """Every published relation in a CSV field appears in that entity card."""
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        source_root = ROOT / 'content' / 'notion'
        relation_fields = {
            'Темы': ('История философии', 'Личности', 'Связь'),
            'Личности': ('Темы', 'История философии'),
            'История философии': ('Темы', 'Личности'),
        }
        total_relations = 0
        for group, keys in relation_fields.items():
            csv_files = list(source_root.rglob(group + ' *' + '_all.csv'))
            self.assertEqual(len(csv_files), 1, group)
            with csv_files[0].open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                # Cards link the same record, but duplicate titles can occur in
                # the original export. Verify each card once, not by title alone.
                name = row['Name']
                kind = {'Темы': 'topics', 'Личности': 'people',
                        'История философии': 'history'}[group]
                cards = re.findall(
                    r'<article class="entity-card entity-card--' + kind + r'">.*?</article>',
                    home, flags=re.DOTALL
                )
                from html import escape as html_escape
                candidates = [
                    card for card in cards
                    if '<span class="entity-card-title">' + html_escape(name) + '</span>' in card
                ]
                self.assertTrue(candidates, f'Catalog card absent: {group} / {name}')
                expected = []
                for key in keys:
                    raw = row.get(key, '').strip()
                    if not raw:
                        continue
                    expected.append('<dt>' + key + '</dt>')
                    for pid in re.findall(r'([a-f0-9]{32})\.md', raw):
                        # Only linkable public entities: unpublished homework and
                        # missing export entries never masquerade as public pages.
                        if pid not in self.slugs:
                            continue
                        expected.append('href="' + self.slugs[pid] + '"')
                        total_relations += 1
                self.assertTrue(any(all(fragment in card for fragment in expected)
                                    for card in candidates),
                                f'Missing one or more relations in {group} / {name}')
        self.assertGreater(total_relations, 0)

    def test_history_approximate_periods_and_single_cross_era_card(self):
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(home.count('class="history-timeline-period"'), 8)
        for period in (
            'VI в. до н. э.', 'V–XV вв.', 'XV–XVIII вв.',
            '1780–1840 гг.', '1801–1900', '1901–1950 гг.',
            '1951–2000 гг.', 'с 2001 года',
        ):
            self.assertIn(period, home)
        # The lone cross-period tradition must be a full-width card.
        self.assertIn('class="history-related"', home)
        related = home.split('class="history-related"', 1)[1].split('</section>', 1)[0]
        if related.count('class="entity-card entity-card--history"') == 1:
            css = (OUT / 'style.css').read_text(encoding='utf-8')
            self.assertIn('.history-related .entity-collection:has(> .entity-card:only-child)', css)

    def test_person_cards_ordered_by_year_of_death(self):
        csv_files = list((ROOT / 'content' / 'notion').rglob('Личности *_all.csv'))
        self.assertEqual(len(csv_files), 1)
        with csv_files[0].open(encoding='utf-8-sig', newline='') as stream:
            people = list(csv.DictReader(stream))

        def death_key(row):
            value = row.get('Год смерти', '').strip()
            match = re.search(r'-?\d{1,4}', value)
            if not match:
                return (1, 0, row['Name'].casefold())
            year = int(match.group())
            if 'до н' in value.casefold() or 'bce' in value.casefold():
                year = -abs(year)
            return (0, year, row['Name'].casefold())

        expected = [row['Name'] for row in sorted(people, key=death_key)]
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        actual = [html_unescape(match) for match in re.findall(
            r'<article class="entity-card entity-card--people">'
            r'<a class="entity-card-main" href="[^"]+">.*?'
            r'<span class="entity-card-title">([^<]+)</span>',
            home, flags=re.DOTALL
        )]
        self.assertEqual(actual, expected)

    def test_explicit_relation_is_bidirectional(self):
        hermeneutics = self.public_page('89ecf3804396453cbc4256966e24aa27')
        gadamer = self.public_page('8fdcb8310a88441da41bce0b8f4857c4')
        self.assertIn(self.slugs['8fdcb8310a88441da41bce0b8f4857c4'], hermeneutics)
        self.assertIn(self.slugs['89ecf3804396453cbc4256966e24aa27'], gadamer)

    def test_home_navigation_and_search(self):
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        # The original quotation is part of Hero; three resources follow it,
        # ahead of the single tab menu, without a duplicate editorial block.
        self.assertEqual(home.count('data-resource-open='), 2)
        self.assertIn('id="resource-dialog"', home)
        self.assertEqual(home.count('class="resource-cards"'), 2)
        self.assertEqual(home.count('class="resource-card"'), 11)
        self.assertIn('class="resource-card-image"', home)
        read_cards = home.split('id="resource-read"', 1)[1].split('</div>', 1)[0]
        self.assertIn('homeHeaderTitleImage_ru_RU.png', read_cards)
        self.assertIn('resource-card-placeholder', read_cards)
        self.assertIn('target="_blank" rel="noopener noreferrer"', read_cards)
        self.assertIn('<h1><span class="hero-project-name"><span class="brand-accessible-name">philoloom</span>', home)
        self.assertIn('Автор: <a href="https://mksddn.ru/" target="_blank"', home)
        self.assertIn('href="https://flsf.maxdudin.ru/" target="_blank"', home)
        self.assertIn('id="search-open"', home)
        self.assertIn('<svg aria-hidden="true" viewBox="0 0 24 24"', home)
        self.assertIn('.museum-search svg { display: block; width: 20px; height: 20px; }', (OUT / 'style.css').read_text(encoding='utf-8'))
        self.assertEqual(home.count('id="search-open"'), 1)
        self.assertIn('class="featured-quote"', home)
        self.assertIn('Человеку, исследующему истину, необходимо хоть один раз в жизни усомниться во всех вещах', home)
        self.assertIn('<figcaption>— Рене Декарт</figcaption>', home)
        self.assertIn('class="resource-tiles"', home)
        self.assertEqual(home.count('class="resource-trigger resource-tile"'), 2)
        self.assertIn('class="resource-tile resource-tile-blog"', home)
        self.assertIn('class="resource-tile-cover"', home)
        self.assertLess(home.index('class="hero-cover"'), home.index('class="featured-quote"'))
        self.assertLess(home.index('class="featured-quote"'), home.index('class="resource-tiles"'))
        self.assertLess(home.index('class="section-nav"'), home.index('class="resource-tiles"'))
        self.assertIn('id="more"', home)
        self.assertIn('class="hero-cover-content"', home.split('class="featured-quote"', 1)[0])
        self.assertNotIn('class="featured-quote"', home.split('id="more"', 1)[1])
        self.assertNotIn('class="footer-resources"', home)
        self.assertNotIn('Философский справочник: темы, история мысли, личности и цитаты.', home)
        self.assertNotIn('class="hero-summary"', home)
        self.assertNotIn('<header>', home)

    def test_detail_excludes_private_assignment_metadata(self):
        entries = json.loads((OUT / 'search.json').read_text())
        entry = next(item for item in entries if item['group'] == 'Темы' and item['title'] == 'Герменевтика')
        page = (OUT / entry['url'] / 'index.html').read_text()
        self.assertNotIn('<dt>Задание</dt>', page)
        self.assertNotIn('<dt>Зачтено</dt>', page)
        self.assertNotIn('<dt>Моя работа</dt>', page)
        self.assertLess(page.index('<article>'), page.index('class="entity-links"'))
        self.assertIn('class="entity-detail entity-detail--topics"', page)
        self.assertIn('class="entity-kicker">Темы</span>', page)
        self.assertIn('class="entity-links-title">Связанные материалы</h2>', page)
        self.assertIn('id="search-open"', page)
        for item in entries:
            address = item['url'].split('#', 1)[0]
            target = OUT / address
            record = (target / 'index.html' if target.is_dir() else target).read_text()
            self.assertNotIn('<dt>Моя работа</dt>', record, item['title'])

    def test_person_details_separate_facts_content_and_relations(self):
        descartes = self.public_page('c4c741fb50874c87a5d2cb4d4def5e50')
        self.assertIn('class="entity-detail entity-detail--people"', descartes)
        self.assertIn('class="entity-facts-list"', descartes)
        self.assertIn('<dt>Год рождения</dt><dd>1596</dd>', descartes)
        self.assertIn('<dt>Год смерти</dt><dd>1650</dd>', descartes)
        self.assertLess(descartes.index('class="entity-facts"'),
                        descartes.index('<article>'))
        self.assertNotIn('class="entity-links"', descartes)
        self.assertNotIn('Также упоминается', descartes)
        self.assertNotIn('Связи и упоминания', descartes)
        self.assertEqual(descartes.count('class="quote-entry"'), 2)
        self.assertIn('<dt>Темы</dt>', descartes)
        self.assertIn('<dt>История философии</dt>', descartes)

    def test_contextual_links_deduplicate_explicit_and_discovered_relations(self):
        hermeneutics = self.public_page('89ecf3804396453cbc4256966e24aa27')
        self.assertIn('<dt>Философы</dt>', hermeneutics)
        self.assertIn('<dt>Исторический контекст</dt>', hermeneutics)
        self.assertEqual(hermeneutics.count('href="' + self.slugs['8fdcb8310a88441da41bce0b8f4857c4'] + '"'), 1)
        self.assertNotIn('Связи и упоминания', hermeneutics)
        self.assertNotIn('Также упоминается', hermeneutics)

        ancient = self.public_page('f79b26bcefbf45a2aa50319cd5dc1858')
        self.assertIn('<dt>Представители</dt>', ancient)
        self.assertIn('<dt>Темы и направления</dt>', ancient)

        gadamer = self.public_page('8fdcb8310a88441da41bce0b8f4857c4')
        self.assertNotIn('class="discovered-links"', gadamer)
        self.assertNotIn('class="entity-links"', gadamer)
        self.assertIn('class="person-context"', gadamer)

    def test_compact_headerless_shell_and_system_theme(self):
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        detail = self.public_page('89ecf3804396453cbc4256966e24aa27')
        css = (OUT / 'style.css').read_text(encoding='utf-8')
        self.assertIn('<h1><span class="hero-project-name"><span class="brand-accessible-name">philoloom</span>', home)
        self.assertEqual(home.count('<h1>'), 1)
        self.assertIn('class="museum-stage"', home)
        self.assertNotIn('class="museum-head"', home)
        self.assertIn('class="hero-artwork" role="img" aria-label="Художественный образ Рене Декарта"', home)
        self.assertNotIn('Марк Аврелий', home)
        self.assertNotIn('Wikimedia Commons</a>', home)
        self.assertIn('url("ui/descartes-hero-dark.webp")', css)
        self.assertIn('url("ui/descartes-hero-light.webp")', css)
        self.assertIn('background-position: 60% 12%', css)
        self.assertIn('--hero-mobile-shade:', css)
        for theme in ('dark', 'light'):
            artwork = OUT / 'ui' / f'descartes-hero-{theme}.webp'
            self.assertTrue(artwork.is_file())
            self.assertLess(artwork.stat().st_size, 50_000)
            with Image.open(artwork) as picture:
                self.assertEqual(picture.format, 'WEBP')
                self.assertEqual(picture.size, (1440, 810))
        self.assertNotIn('id="theme-toggle"', home)
        self.assertIn('class="catalog-toolbar"', home)
        self.assertIn('prefers-color-scheme: light', home)
        self.assertEqual(home.count('class="section-nav"'), 1)
        self.assertIn('id="reference-nav"', home)
        self.assertEqual(home.count('class="featured-quote"'), 1)
        self.assertEqual(home.count('data-resource-open='), 2)
        self.assertNotIn('class="home-source-strip"', home)
        self.assertIn('aria-label="Разделы"', home)
        # No sales-like CTAs, cards framing the hero or duplicated navigation.
        for fragment in ('class="museum-frame"', 'class="museum-shortcuts"',
                         'class="museum-top-nav"', 'class="hero-explore"',
                         'class="editorial-spotlight"', 'class="editorial-topic"',
                         'class="editorial-shelf"', 'class="editorial-lead"',
                         'id="about-philoloom"', 'КОЛЛЕКЦИЯ / ТЕМЫ',
                         'Начните с этих идей', 'Исследуйте философию'):
            self.assertNotIn(fragment, home)
        self.assertIn('class="detail-navigation"', detail)
        self.assertNotIn('detail-masthead', detail)
        self.assertNotIn('id="theme-toggle"', detail)
        self.assertNotIn('data-reader-toggle', detail)
        self.assertNotIn('reading-controls', css)
        self.assertNotIn('reader-mode', css)
        self.assertEqual(detail.count('id="search-open"'), 1)
        self.assertIn('<article>', detail)
        self.assertIn('name="description"', detail)
        self.assertNotIn('class="hero-cover"', detail)
        self.assertIn(':root[data-theme="light"]', css)
        self.assertIn('html.tabs-ready .section-heading', css)
        self.assertIn('@media (max-width: 650px)', css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        self.assertIn(':focus-visible', css)

    def test_brand_logo_and_favicon_are_published(self):
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        detail = self.public_page('89ecf3804396453cbc4256966e24aa27')
        self.assertIn('class="hero-brand-watermark" aria-hidden="true"', home)
        self.assertNotIn('class="hero-brand-mark"', home)
        css = (OUT / 'style.css').read_text(encoding='utf-8')
        self.assertIn('background: url("ui/philoloom-tree-hero.svg")', css)
        self.assertIn('mask: url("ui/philoloom-wordmark.svg")', css)
        self.assertIn('class="brand-accessible-name">philoloom</span>', home)
        self.assertIn('class="hero-wordmark" aria-hidden="true"', home)
        self.assertNotIn('url("ui/philoloom-tree.webp")', css)
        for name in ('philoloom-tree-hero.svg', 'philoloom-wordmark.svg'):
            asset = OUT / 'ui' / name
            self.assertTrue(asset.is_file(), name)
            source = asset.read_text(encoding='utf-8')
            self.assertIn('<svg', source)
            self.assertIn('viewBox=', source)
            self.assertIn('<path', source)
        self.assertIn('>philoloom</span>', home)
        self.assertIn('rel="icon" type="image/svg+xml" href="favicon.svg"', home)
        self.assertIn('rel="icon" type="image/svg+xml" href="favicon.svg"', detail)
        self.assertIn('property="og:site_name" content="philoloom"', home)
        self.assertTrue((OUT / 'favicon.svg').is_file())
        self.assertIn('<svg', (OUT / 'favicon.svg').read_text(encoding='utf-8'))
        for name in ('philoloom-tree.webp', 'philoloom-approved.webp'):
            asset = OUT / 'ui' / name
            self.assertTrue(asset.is_file(), name)
            with Image.open(asset) as picture:
                self.assertEqual(picture.format, 'WEBP')

    def test_only_optimized_local_rasters_are_published(self):
        images = [p for p in OUT.rglob('*') if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}]
        self.assertTrue(images)
        for path in images:
            self.assertEqual(path.suffix, '.webp', path)
            with Image.open(path) as image:
                image.verify()
        for info in self.manifest['sources'].values():
            self.assertLessEqual(info['variants'][0]['width'], info['variants'][-1]['width'])
            for variant in info['variants']:
                with Image.open(OUT / variant['url']) as image:
                    self.assertEqual(image.size, (variant['width'], variant['height']))

    def test_cover_payload_and_text_diagram_quality(self):
        info = self.manifest['sources']['site/assets/forest-cover.jpg']
        self.assertLess(info['variants'][-1]['bytes'], info['original_bytes'] / 4)
        for relative, info in self.manifest['sources'].items():
            if relative.startswith('content/notion/'):
                with Image.open(ROOT / relative) as original:
                    original = ImageOps.exif_transpose(original).convert('RGBA')
                with Image.open(OUT / info['variants'][-1]['url']) as optimized:
                    self.assertEqual(original.size, optimized.size)
                    difference = ImageChops.difference(original, optimized.convert('RGBA'))
                    self.assertIsNone(difference.convert('RGB').getbbox())
                    self.assertIsNone(difference.getchannel('A').getbbox())

    def test_optimizer_reuses_unchanged_files(self):
        paths = list((ROOT / 'content/optimized').glob('*.webp'))
        before = {path: path.stat().st_mtime_ns for path in paths}
        manifest_before = (ROOT / 'content/image-manifest.json').read_bytes()
        subprocess.run([sys.executable, str(ROOT / 'scripts/optimize_images.py')], check=True, capture_output=True)
        self.assertEqual(manifest_before, (ROOT / 'content/image-manifest.json').read_bytes())
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in paths})


if __name__ == '__main__':
    unittest.main()
