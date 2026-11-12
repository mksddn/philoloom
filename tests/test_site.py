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
        home = (OUT / 'index.html').read_text()
        self.assertEqual(home.count('<section class="hero-tile'), 4)
        self.assertIn('Что посмотреть', home)
        self.assertIn('Что почитать', home)
        self.assertIn('Автор: Макс Дудин', home)
        self.assertNotIn('<header>', home)
        self.assertIn('id="search-open"', home)

    def test_detail_excludes_private_assignment_metadata(self):
        entries = json.loads((OUT / 'search.json').read_text())
        entry = next(item for item in entries if item['group'] == 'Темы')
        page = (OUT / entry['url']).read_text()
        self.assertNotIn('<dt>Задание</dt>', page)
        self.assertNotIn('<dt>Зачтено</dt>', page)
        self.assertIn('id="search-open"', page)

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
