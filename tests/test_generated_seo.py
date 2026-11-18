"""Regression checks for SEO metadata and navigational duplication in generated HTML."""
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image

DIST = Path(__file__).resolve().parents[1] / 'dist'
BASE = 'https://mksddn.github.io/philoloom/'


class PageInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonical = []
        self.descriptions = []
        self.og_urls = []
        self.meta = {}
        self.schema = []
        self.breadcrumb_labels = []
        self._schema = False
        self._crumb = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key:
                self.meta.setdefault(key, []).append(attrs.get('content', ''))

        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('name') == 'description':
            self.descriptions.append(attrs.get('content'))
        if tag == 'meta' and attrs.get('property') == 'og:url':
            self.og_urls.append(attrs.get('content'))
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self._schema = True
        if tag == 'nav' and 'page-breadcrumbs' in attrs.get('class', '').split():
            self._crumb = True
        if self._crumb and tag == 'a':
            self.breadcrumb_labels.append(None)
        if self._crumb and attrs.get('aria-current') == 'page':
            self.breadcrumb_labels.append(None)

    def handle_data(self, data):
        if self._schema:
            self.schema.append(data)
        if self._crumb and self.breadcrumb_labels and self.breadcrumb_labels[-1] is None and data.strip():
            self.breadcrumb_labels[-1] = data.strip()

    def handle_endtag(self, tag):
        if tag == 'script':
            self._schema = False
        if tag == 'nav':
            self._crumb = False


class GeneratedSeoTests(unittest.TestCase):
    def assert_social_image(self, parser, expected_url, expected_type):
        meta = parser.meta
        self.assertEqual(meta.get('og:type'), [expected_type])
        self.assertEqual(meta.get('og:locale'), ['ru_RU'])
        self.assertEqual(meta.get('og:site_name'), ['philoloom'])
        self.assertEqual(meta.get('og:url'), [expected_url])
        self.assertEqual(meta.get('og:image'), [expected_url.replace(
            BASE, BASE + 'og/', 1).removesuffix('/') + '.jpg'
            if expected_url != BASE else BASE + 'og/home.jpg'])
        image_url = meta['og:image'][0]
        self.assertEqual(meta.get('og:image:secure_url'), [image_url])
        self.assertEqual(meta.get('og:image:type'), ['image/jpeg'])
        self.assertEqual(meta.get('og:image:width'), ['1200'])
        self.assertEqual(meta.get('og:image:height'), ['630'])
        self.assertEqual(len(meta.get('og:image:alt', [])), 1)
        self.assertTrue(meta['og:image:alt'][0].strip())
        self.assertEqual(meta.get('twitter:card'), ['summary_large_image'])
        self.assertEqual(meta.get('twitter:image'), [image_url])
        self.assertEqual(meta.get('twitter:image:alt'), meta['og:image:alt'])
        self.assertEqual(meta.get('twitter:title'), meta.get('og:title'))
        self.assertEqual(meta.get('twitter:description'), meta.get('og:description'))
        self.assertEqual(meta.get('og:description'), meta.get('description'))
        self.assertTrue(image_url.startswith(BASE))
        self.assertNotIn('?', image_url)
        file_path = DIST / image_url[len(BASE):]
        self.assertTrue(file_path.is_file(), image_url)
        self.assertLess(file_path.stat().st_size, 5_000_000)
        with Image.open(file_path) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (1200, 630))
            image.verify()

    def test_home_social_image(self):
        page = DIST / 'index.html'
        self.assertTrue(page.is_file())
        parser = PageInspector()
        parser.feed(page.read_text(encoding='utf-8'))
        self.assert_social_image(parser, BASE, 'website')

    def test_all_entity_pages(self):
        pages = sorted(DIST.glob('*/**/index.html'))
        self.assertTrue(pages, 'Build the site before running SEO checks')
        for path in pages:
            with self.subTest(page=str(path.relative_to(DIST))):
                html = path.read_text(encoding='utf-8')
                parser = PageInspector()
                parser.feed(html)
                expected = BASE + path.relative_to(DIST).parent.as_posix() + '/'
                self.assertEqual(parser.canonical, [expected])
                self.assertEqual(parser.og_urls, [expected])
                self.assert_social_image(parser, expected, 'article')
                self.assertEqual(len(parser.descriptions), 1)
                self.assertTrue(0 < len(parser.descriptions[0]) <= 170)
                self.assertEqual(len(parser.schema), 1)
                data = json.loads(parser.schema[0])
                self.assertEqual(data['url'], expected)
                self.assertEqual(data['breadcrumb']['@type'], 'BreadcrumbList')
                items = data['breadcrumb']['itemListElement']
                self.assertEqual([x['position'] for x in items], list(range(1, len(items) + 1)))
                self.assertEqual([x['name'] for x in items[:-1]], parser.breadcrumb_labels)
                self.assertEqual(items[-1]['item'], expected)
                self.assertNotIn('\\\\n', html, 'Literal escaped newline in generated HTML')
                self.assertNotRegex(html, r'<section class="entity-links"[^>]*>\\s*</section>')


if __name__ == '__main__':
    unittest.main()
