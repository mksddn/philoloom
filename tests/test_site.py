"""Integration checks for the generated reference and its image pipeline."""
import json
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

    def test_all_pages_and_local_links_exist(self):
        entries = json.loads((OUT / 'search.json').read_text())
        self.assertEqual(len(entries), len([p for p in (ROOT / 'content/notion').rglob('*.md') if p.parent.name != 'Самостоятельная работа']))
        self.assertFalse(any(entry['group'] == 'Самостоятельная работа' for entry in entries))
        for entry in entries:
            path = OUT / entry['url']
            self.assertTrue(path.is_file(), entry['title'])
            page = Page(path.read_text())
            self.assertEqual(len(page.ids), len(set(page.ids)), entry['title'])
            for link in page.links:
                parsed = urlsplit(link)
                if not parsed.scheme and parsed.path:
                    self.assertTrue((OUT / unquote(parsed.path)).is_file(), (entry['title'], link))

    def test_sections_remain_in_static_html(self):
        source = (OUT / 'index.html').read_text()
        self.assertEqual(source.count('class="reference-section"'), 4)
        self.assertNotIn('💪 Мои статьи', source)
        self.assertEqual(source.count('data-view-content='), 12)
        self.assertNotIn('class="reference-section" hidden', source)

    def test_explicit_relation_is_bidirectional(self):
        hermeneutics = (OUT / '89ecf3804396453cbc4256966e24aa27.html').read_text()
        gadamer = (OUT / '8fdcb8310a88441da41bce0b8f4857c4.html').read_text()
        self.assertIn('8fdcb8310a88441da41bce0b8f4857c4.html', hermeneutics.split('class="entity-links"', 1)[1])
        self.assertIn('89ecf3804396453cbc4256966e24aa27.html', gadamer.split('class="entity-links"', 1)[1])

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
        self.assertIn('<h1><span class="hero-project-name">PhiloLoom</span> <span class="hero-title-text">', home)
        self.assertIn('Автор: <a href="https://mksddn.ru/" target="_blank"', home)
        self.assertIn('href="https://flsf.maxdudin.ru/" target="_blank"', home)
        self.assertIn('id="search-open"', home)
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
        self.assertLess(home.index('class="resource-tiles"'), home.index('class="section-nav"'))
        self.assertIn('class="hero-cover-content"', home.split('class="featured-quote"', 1)[0])
        self.assertNotIn('class="featured-quote"', home.split('class="home-source-strip"', 1)[1])
        self.assertNotIn('class="footer-resources"', home)
        self.assertNotIn('Философский справочник: темы, история мысли, личности и цитаты.', home)
        self.assertNotIn('class="hero-summary"', home)
        self.assertNotIn('<header>', home)

    def test_detail_excludes_private_assignment_metadata(self):
        entries = json.loads((OUT / 'search.json').read_text())
        entry = next(item for item in entries if item['group'] == 'Темы')
        page = (OUT / entry['url']).read_text()
        self.assertNotIn('<dt>Задание</dt>', page)
        self.assertNotIn('<dt>Зачтено</dt>', page)
        self.assertNotIn('<dt>Моя работа</dt>', page)
        self.assertLess(page.index('class="entity-links"'), page.index('<article>'))
        self.assertIn('id="search-open"', page)
        for item in entries:
            record = (OUT / item['url']).read_text()
            self.assertNotIn('<dt>Моя работа</dt>', record, item['title'])

    def test_compact_headerless_shell_and_system_theme(self):
        home = (OUT / 'index.html').read_text(encoding='utf-8')
        detail = (OUT / '89ecf3804396453cbc4256966e24aa27.html').read_text(encoding='utf-8')
        css = (OUT / 'style.css').read_text(encoding='utf-8')
        self.assertIn('<h1><span class="hero-project-name">PhiloLoom</span>', home)
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
        self.assertIn('class="home-source-strip"', home)
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
