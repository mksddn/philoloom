"""Build a portable static reference from the original Notion export."""
import csv
import hashlib
import html
import json
import re
import shutil
from xml.etree import ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser
import markdown

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / 'content' / 'notion'
OUT = ROOT / 'dist'
SITE_URL = 'https://mksddn.github.io/philoloom/'
GROUPS = [('Темы', 'Темы'), ('История философии', 'История философии'),
          ('Цитаты', 'Цитаты'), ('Личности', 'Личности')]
# Retain exported homework metadata for direct article URLs, but no public section.
SOURCE_GROUPS = GROUPS + [('Самостоятельная работа', '💪 Мои статьи')]
ID = re.compile(r'([a-f0-9]{32})(?:_all)?\.(?:md|csv)$')
escape = html.escape
PREVIEWS = ROOT / 'content' / 'link-previews.json'
previews = json.loads(PREVIEWS.read_text(encoding='utf-8')) if PREVIEWS.exists() else {}
pages = {}
for path in sorted(CONTENT.rglob('*.md')):
    match = ID.search(path.name)
    if not match:
        raise ValueError(f'Page has no stable ID: {path.name}')
    text = path.read_text(encoding='utf-8')
    title = text.splitlines()[0].removeprefix('# ').strip()
    pages[match[1]] = dict(id=match[1], path=path, title=title, text=text,
                         group=path.parent.name if path.parent != CONTENT else '')
home = next(p for p in pages.values() if not p['group'])
databases = {}
for path in CONTENT.rglob('*_all.csv'):
    name = re.sub(r' [a-f0-9]{32}_all$', '', path.stem)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        databases[name] = list(csv.DictReader(stream))
db_ids = {ID.search(p.name)[1]: re.sub(r' [a-f0-9]{32}_all$', '', p.stem)
          for p in CONTENT.rglob('*_all.csv')}
assets = {p.resolve(): 'assets/' + p.relative_to(CONTENT).as_posix()
          for p in CONTENT.rglob('*') if p.is_file() and p.suffix not in ('.md', '.csv')}

IMAGE_MANIFEST = ROOT / 'content' / 'image-manifest.json'
image_manifest = json.loads(IMAGE_MANIFEST.read_text(encoding='utf-8')) if IMAGE_MANIFEST.exists() else {'sources': {}}
optimized_sources = image_manifest['sources']
variant_sources = {variant['url']: info for info in optimized_sources.values() for variant in info['variants']}


def image_info(url):
    decoded = unquote(url)
    if decoded in variant_sources:
        return variant_sources[decoded]
    for prefix, source in [('previews/', 'content/previews/'), ('ui/', 'site/assets/'), ('assets/', 'content/notion/')]:
        if decoded.startswith(prefix):
            return optimized_sources.get(source + decoded[len(prefix):])
    return None


def image_url(url):
    info = image_info(url)
    return info['variants'][-1]['url'] if info else url


def image_html(url, css_class='', sizes='(max-width: 700px) 100vw, 700px', priority=False):
    info = image_info(url)
    attrs = f' class="{escape(css_class, quote=True)}"' if css_class else ''
    if info:
        variants = info['variants']
        largest = variants[-1]
        srcset = ', '.join(f"{item['url']} {item['width']}w" for item in variants)
        attrs += (f' srcset="{escape(srcset,quote=True)}" sizes="{escape(sizes,quote=True)}"'
                  f' width="{largest["width"]}" height="{largest["height"]}" data-full-src="{largest["url"]}"')
        url = largest['url']
    loading = 'fetchpriority="high"' if priority else 'loading="lazy"'
    return f'<img{attrs} src="{escape(url,quote=True)}" alt="" {loading} decoding="async" referrerpolicy="no-referrer">'


def local_portrait(page, fallback):
    if page['group'] == 'Личности':
        for url, metadata in previews.items():
            if metadata.get('local_image') and url in page['text']:
                return metadata['local_image']
    return fallback


def safe_url(url):
    return urlsplit(url).scheme.lower() in ('', 'https', 'http', 'mailto') and not url.startswith('//')

def resolve(url, page):
    decoded = unquote(url)
    if urlsplit(decoded).scheme:
        return url if safe_url(url) else '#'
    match = ID.search(decoded)
    if match:
        pid = match[1]
        if pid in pages:
            return 'index.html' if pid == home['id'] else pid + '.html'
        if pid in db_ids:
            return 'index.html#' + pid
    candidate = (page['path'].parent / decoded).resolve()
    if candidate in assets:
        from urllib.parse import quote
        return quote(image_url(assets[candidate]))
    return url if safe_url(url) else '#'

class CleanHTML(HTMLParser):
    """Keep Markdown presentation while removing executable HTML and unsafe URLs."""
    allowed = set('p div span a img h1 h2 h3 h4 h5 h6 blockquote pre code ul ol li table thead tbody tr th td hr br strong em del details summary input'.split())
    void = {'img', 'hr', 'br', 'input'}
    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.page, self.output = page, []
    def handle_starttag(self, tag, attrs):
        if tag not in self.allowed:
            return
        if tag == 'img':
            values = dict(attrs)
            source = values.get('src','')
            if source and safe_url(source):
                source = resolve(local_portrait(self.page, source), self.page)
                markup = image_html(source)
                alt = values.get('alt','')
                markup = markup.replace('alt=""', f'alt="{escape(alt,quote=True)}"', 1)
                self.output.append(markup)
            return
        clean = []
        for key, value in attrs:
            if key in ('href', 'src') and value and safe_url(value):
                clean.append((key, resolve(value, self.page)))
            elif key in ('alt', 'title', 'colspan', 'rowspan', 'start', 'id'):
                clean.append((key, value or ''))
        self.output.append('<' + tag + ''.join(f' {k}="{escape(v, quote=True)}"' for k,v in clean) + '>')
    def handle_endtag(self, tag):
        if tag in self.allowed and tag not in self.void:
            self.output.append('</' + tag + '>')
    def handle_data(self, data):
        self.output.append(escape(data))

def render(text, page):
    parser = CleanHTML(page)
    parser.feed(markdown.markdown(text, extensions=['tables', 'fenced_code', 'sane_lists']))
    return enrich_bookmarks(''.join(parser.output), page)

def bookmark(url, label, page):
    metadata = previews.get(html.unescape(url), {})
    title = html.unescape(re.sub('<[^>]*>', '', label)) or metadata.get('title', '')
    description = metadata.get('description', '')
    image = metadata.get('local_image') or metadata.get('image', '')
    # A philosopher's explicit portrait is the best fallback for their biography link.
    if not image and 'wikipedia.org/wiki/' in url:
        portrait = re.search(r'!\[[^\]]*\]\((https?://[^\s]+)\)', page['text'])
        image = portrait[1] if portrait else ''
    media = (f'<span class="bookmark-media">{image_html(image, sizes="(max-width: 700px) 30vw, 230px")}</span>'
             if image and safe_url(image) else '')
    description_html = f'<span class="bookmark-description">{escape(description)}</span>' if description else ''
    domain = urlsplit(html.unescape(url)).netloc
    return (f'<a class="bookmark" href="{escape(html.unescape(url),quote=True)}">'
            f'<span class="bookmark-copy"><span class="bookmark-title">{escape(title)}</span>{description_html}'
            f'<span class="bookmark-domain">{escape(domain)}</span></span>{media}</a>')


def enrich_bookmarks(content, page):
    return re.sub(r'<p><a href="(https?://[^"<>]+)">([^<]+)</a></p>',
                  lambda m: bookmark(m[1],m[2],page), content)


# CSV relations contain links with balanced parentheses in exported filenames.
def property_html(value, page):
    pattern = re.compile(r'([^\n]*?) \(([^\s]*?[a-f0-9]{32}\.md)\)(?:, |$)')
    parts, end = [], 0
    for m in pattern.finditer(value):
        if m.start() > end:
            parts.append(escape(value[end:m.start()]))
        target = ID.search(unquote(m[2]))
        if target and target[1] not in pages:
            parts.append(f'<span class="empty">{escape(m[1])} (нет в экспорте)</span>')
        else:
            parts.append(f'<a class="relation" href="{escape(resolve(m[2],page),quote=True)}">{escape(m[1])}</a>')
        end = m.end()
    if parts:
        parts.append(escape(value[end:]))
        return ''.join(parts)
    if value.startswith(('https://', 'http://')) and safe_url(value):
        return f'<a href="{escape(value,quote=True)}">{escape(value)}</a>'
    return escape(value) if value else ''

def matching_page(group, row):
    matches = [p for p in pages.values() if p['group'] == group and p['title'] == row['Name']]
    # Preserve the empty duplicate as a separate entry, in export order.
    for p in matches:
        if p['id'] not in assigned:
            assigned.add(p['id'])
            return p
    raise ValueError(f'No page for {group}: {row["Name"]}')

assigned = set()
rows_by_id = {}
ordered = {}
for group,_ in SOURCE_GROUPS:
    ordered[group] = []
    for row in databases[group]:
        p = matching_page(group, row)
        ordered[group].append(p)
        rows_by_id[p['id']] = row

nav = ''.join(f'<a href="index.html#{next(i for i,n in db_ids.items() if n==g)}">{label}</a>' for g,label in GROUPS)

# The visual identity is a presentation layer; content remains sourced from Notion.
SEARCH_BUTTON = ('<button id="search-open" class="museum-search" type="button" '
                 'aria-label="Открыть поиск по справочнику" aria-haspopup="dialog" '
                 'aria-controls="search-dialog" title="Поиск">'
                 '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                 '<circle cx="11" cy="11" r="7"></circle><path d="m20 20-4-4"></path></svg></button>')
# Theme-specific illustrations of René Descartes were approved for this Hero.
# They are artistic interpretations, not photographs of historical objects.
# Their local WebP files are referenced through theme-aware CSS.


def shell(title, body, group='', hero_quote='', canonical_path=''):
    # Project identity belongs inside the home page's main heading.
    cover = (f'<div class="museum-stage"><div class="hero-cover">'
             f'<div class="hero-artwork" role="img" '
             f'aria-label="Художественный образ Рене Декарта"></div>'
             f'<div class="hero-orbit" aria-hidden="true"></div>'
             f'<div class="hero-brand-watermark" aria-hidden="true"></div>'
             f'<div class="hero-cover-content">'
             f'<h1><span class="hero-project-name">'
             f'<span class="brand-accessible-name">philoloom</span>'
             f'<span class="hero-wordmark" aria-hidden="true"></span></span> '
             f'<span class="hero-title-text">Атлас философской мысли</span></h1>'
             f'{hero_quote}</div></div></div>') if not group else ''
    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="theme-color" content="#0f0f0f">
<title>{escape(title)} · philoloom</title>
<link rel="canonical" href="{escape(SITE_URL + canonical_path, quote=True)}">
<meta name="description" content="{escape("Исследуйте философские идеи, мыслителей и связи между ними." if not group else title + " — история философии, направления и мыслители в справочнике philoloom.", quote=True)}">
<script>const previewTheme = new URLSearchParams(location.search).get('theme'); document.documentElement.dataset.theme = ['light', 'dark'].includes(previewTheme) ? previewTheme : (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');</script>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<meta property="og:site_name" content="philoloom">
<link rel="stylesheet" href="style.css">
<script src="app.js" defer></script>
</head>
<body>
<a class="skip" href="#main">К содержимому</a>
<main id="main" class="{'home-page' if not group else 'detail-page'}">{cover + '<div class="site-container home-inner">' + body + '</div>' if not group else body}</main>
<footer><div class="site-container">philoloom · Философский справочник · Автор: <a href="https://mksddn.ru/" target="_blank" rel="author noopener noreferrer">Макс Дудин</a></div></footer>
<dialog id="page-panel" aria-label="Подробности страницы">
<div class="panel-toolbar">
<button id="panel-back" aria-label="Назад в панели">←</button>
<button id="panel-next" aria-label="Следующая запись">↓</button>
<a id="panel-full" data-full-page aria-label="Открыть на всю страницу" title="Открыть на всю страницу">↗</a>
<button id="panel-close" aria-label="Закрыть подробности">×</button>
</div>
<div id="panel-path" class="panel-path"></div>
<div id="panel-content" class="panel-content" aria-live="polite">
</div>
</dialog>
<dialog id="image-dialog" aria-label="Просмотр изображения">
<button id="image-close" aria-label="Закрыть изображение">×</button>
<img id="image-full" alt="">
</dialog>
{resource_dialog if not group else ""}
<dialog id="search-dialog" aria-label="Поиск по справочнику">
<form method="dialog">
<label for="query">Поиск по справочнику</label>
<button aria-label="Закрыть поиск">×</button>
</form>
<input id="query" type="search" placeholder="Тема, философ или фрагмент текста…" autocomplete="off">
<p id="search-status" role="status"></p>
<ul id="results"></ul>
</dialog>
</body>
</html>'''

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir()
def copy_asset(source, target):
    with source.open('rb') as stream:
        if stream.read(100).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise RuntimeError('Missing Git LFS image contents. Run git lfs install and git lfs pull before building.')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


for relative, info in optimized_sources.items():
    source = ROOT / relative
    if hashlib.sha256(source.read_bytes()).hexdigest() != info['sha256']:
        raise RuntimeError('Image source changed or is a Git LFS pointer. Run git lfs pull and python3 scripts/optimize_images.py.')
    for variant in info['variants']:
        source = ROOT / 'content' / 'optimized' / Path(variant['url']).name
        copy_asset(source, OUT / variant['url'])
for folder, destination in [('site/assets', 'ui'), ('content/previews', 'previews')]:
    for source in (ROOT / folder).rglob('*'):
        if source.is_file() and source.relative_to(ROOT).as_posix() not in optimized_sources:
            copy_asset(source, OUT / destination / source.relative_to(ROOT / folder))
for source, dest in assets.items():
    if source.relative_to(ROOT).as_posix() not in optimized_sources:
        copy_asset(source, OUT / dest)
copy_asset(ROOT / 'site' / 'favicon.svg', OUT / 'favicon.svg')
for name in ('style.css', 'app.js'):
    shutil.copyfile(ROOT / 'site' / name, OUT / name)

def page_parts(page):
    lines = page['text'].splitlines()[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    properties = []
    while lines and re.match(r'^[^#>\-*\[\n]{1,35}: ', lines[0]):
        properties.append(lines.pop(0).split(': ', 1))
    return properties, '\n'.join(lines)


connections = {pid: set() for pid in pages}
for pid, page in pages.items():
    values = [value for key, value in rows_by_id.get(pid, {}).items() if key not in ('Name', 'Конспект', 'Задание')]
    values.append(page_parts(page)[1])
    for related_id in set(re.findall(r'([a-f0-9]{32})\.md', unquote(' '.join(values)))):
        if related_id in pages and related_id != pid:
            connections[pid].add(related_id)
            connections[related_id].add(pid)


def related_records(page, props):
    # Explicit relations already appear in metadata; only show additional backlinks.
    explicit = set()
    for key, value in props:
        if key in ('Личности', 'Темы', 'История философии', 'Связь', 'Связанные записи'):
            explicit.update(re.findall(r'([a-f0-9]{32})\.md', unquote(value)))
    linked = sorted((pages[pid] for pid in connections[page['id']] if pid not in explicit
                     and pages[pid]['group'] != 'Самостоятельная работа'),
                    key=lambda p: (p['group'] != 'Темы', p['group'], p['title'].casefold()))
    if not linked:
        return ''
    def items(records):
        return '<ul>' + ''.join(f'<li><a href="{p["id"]}.html"><span>{escape(p["title"])}</span><small>{escape(p["group"])}</small></a></li>' for p in records) + '</ul>'
    content = items(linked[:10])
    if len(linked) > 10:
        content += f'<details><summary>Ещё {len(linked)-10}</summary>{items(linked[10:])}</details>'
    return '<div class="discovered-links"><h3>Также упоминается</h3><p>Автоматически найденные ссылки из других материалов справочника.</p>' + content + '</div>'


def breadcrumbs(page):
    group_id = next((pid for pid, group in db_ids.items() if group == page['group']), '')
    group_link = f'<a href="index.html#{group_id}">{escape(page["group"])}</a>' if group_id else ''
    return (f'<nav class="back page-breadcrumbs" aria-label="Путь по справочнику"><a href="index.html">philoloom</a>'
            f'<span aria-hidden="true">/</span>{group_link}<span aria-hidden="true">/</span>'
            f'<span aria-current="page" title="{escape(page["title"],quote=True)}">{escape(page["title"])}</span></nav>')



for p in pages.values():
    if p == home:
        continue
    props, body_text = page_parts(p)
    row = rows_by_id.get(p['id'])
    if row:
        props = [(k,v) for k,v in row.items() if k != 'Name']
    hidden_meta = {'Конспект', 'Задание', 'Зачтено', 'Моя работа', 'Связанные записи'}
    props = [(k,v) for k,v in props if v.strip() and k not in hidden_meta and not k.startswith('Самостоятельная работа')]
    # Keep explicit relations including "Связь"; these are meaningful public navigation.
    table = '<dl class="properties">' + ''.join(f'<dt>{escape(k)}</dt><dd>{property_html(v,p)}</dd>' for k,v in props) + '</dl>' if props else ''
    extra = related_records(p, props)
    connections_html = f'<section class="entity-links" aria-label="Связи и упоминания">{table}{extra}</section>' if table or extra else ''
    quote_class = ' class="quote-heading"' if p['group'] == 'Цитаты' else ''
    body = (f'<div class="detail-navigation">{breadcrumbs(p)}{SEARCH_BUTTON}</div>'
            f'<h1{quote_class}>{escape(p["title"])}</h1>{connections_html}<article>{render(body_text,p)}</article>')
    (OUT / (p['id'] + '.html')).write_text(shell(p['title'],body,p['group'],canonical_path=p['id'] + '.html'),encoding='utf-8')

# Preserve the exact published quotation and resources from the untouched
# Notion introduction; none of these are newly authored philosophical claims.
intro = home['text'].split('\n## ')[0]
quote_source = intro.split('- Посмотреть', 1)[0].splitlines()[1:]
quote_lines = [line.strip() for line in quote_source if line.strip() and line.strip() != '>']
quote_text = next((re.sub(r'^>\s*|\*\*', '', line) for line in quote_lines if line.startswith('>')), '')
quote_author = next((line for line in quote_lines if not line.startswith('>')), '')
if not quote_text or not quote_author:
    raise ValueError('The original Descartes quotation is missing from the source introduction')
quote_html = (f'<figure class="featured-quote"><span class="quote-ornament" aria-hidden="true">“</span>'
              f'<blockquote><p>{escape(quote_text)}</p></blockquote>'
              f'<figcaption>— {escape(quote_author)}</figcaption></figure>')

def resource_cards(markdown_text):
    cards = []
    for label, url in re.findall(r'\[([^]]+)\]\((https?://[^)]+)\)', markdown_text):
        if not safe_url(url):
            continue
        meta = previews.get(url, {})
        domain = urlsplit(url).netloc.removeprefix('www.')
        image = meta.get('local_image') or meta.get('image') or ''
        media = (f'<span class="resource-card-media">{image_html(image, "resource-card-image", sizes="(max-width: 650px) 88px, 160px")}</span>'
                 if image and safe_url(image) else
                 f'<span class="resource-card-media resource-card-placeholder" aria-hidden="true">{escape(domain[:1].upper())}</span>')
        description = (meta.get('description') or '').strip()
        if description.startswith(('Делитесь видео с близкими', 'Share your videos')):
            description = ''
        description_html = f'<span class="resource-card-description">{escape(description[:155])}</span>' if description else ''
        cards.append(f'<li><a class="resource-card" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                     f'{media}<span class="resource-card-copy"><strong>{escape(label)}</strong>'
                     f'{description_html}<small>{escape(domain)}</small></span>'
                     f'<span class="resource-card-arrow" aria-hidden="true">↗</span></a></li>')
    return '<ul class="resource-cards">' + ''.join(cards) + '</ul>'

watch = intro.split('- Посмотреть', 1)[1].split('- 📗', 1)[0] if '- Посмотреть' in intro else ''
read = intro.split('- 📗', 1)[1].split('[Блог о философии]', 1)[0] if '- 📗' in intro else ''
resource_dialog = ('<dialog id="resource-dialog" aria-labelledby="resource-title">'
                   '<div class="resource-toolbar"><h2 id="resource-title">Материалы</h2><button type="button" id="resource-close" aria-label="Закрыть">×</button></div>'
                   f'<div id="resource-watch" class="resource-list" hidden>{resource_cards(watch)}</div>'
                   f'<div id="resource-read" class="resource-list" hidden>{resource_cards(read)}</div>'
                   '</dialog>')
# Resource tiles live immediately below Hero; the original quotation is shown
# inside the Hero, ahead of the single encyclopedia tab menu.
blog_url = 'https://flsf.maxdudin.ru/'
blog_meta = previews.get(blog_url, {})
blog_image = blog_meta.get('local_image') or blog_meta.get('image') or ''
blog_media = (f'<span class="resource-tile-art">{image_html(blog_image, "resource-tile-cover", sizes="(max-width: 650px) 100px, 200px")}</span>'
              if blog_image and safe_url(blog_image) else '')
watch_count = len(re.findall(r'\[[^]]+\]\(https?://[^)]+\)', watch))
read_count = len(re.findall(r'\[[^]]+\]\(https?://[^)]+\)', read))
resources = (
    '<div class="resource-tiles" aria-label="Дополнительные материалы">'
    '<button type="button" class="resource-trigger resource-tile" data-resource-open="watch" '
    'aria-haspopup="dialog" aria-controls="resource-dialog">'
    f'<span class="resource-tile-title">Видео</span>'
    f'<small>{watch_count} подборки</small>'
    '<span class="resource-tile-arrow" aria-hidden="true">↗</span></button>'
    '<button type="button" class="resource-trigger resource-tile" data-resource-open="read" '
    'aria-haspopup="dialog" aria-controls="resource-dialog">'
    f'<span class="resource-tile-title">Библиотека</span>'
    f'<small>{read_count} источников</small>'
    '<span class="resource-tile-arrow" aria-hidden="true">↗</span></button>'
    f'<a class="resource-tile resource-tile-blog" href="{blog_url}" target="_blank" rel="noopener noreferrer">'
    f'{blog_media}<span class="resource-tile-description">'
    f'<span class="resource-tile-title">Блог о философии</span>'
    f'<small>flsf.maxdudin.ru</small></span>'
    '<span class="resource-tile-arrow" aria-hidden="true">↗</span></a>'
    '</div>'
)
body = (f'<div class="home-source-strip" aria-label="Дополнительные материалы">'
        f'{resources}</div>'
        f'<div class="catalog-toolbar"><nav id="reference-nav" class="section-nav" aria-label="Разделы">{nav}</nav>{SEARCH_BUTTON}</div>')

class MediaLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.images, self.links = [], []
        self.feed(markdown.markdown(text))
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img' and attrs.get('src'):
            self.images.append(attrs['src'])
        elif tag == 'a' and attrs.get('href','').startswith(('http://','https://')):
            self.links.append(attrs['href'])


def page_image(page):
    media = MediaLinks(page['text'])
    # Only display an explicitly embedded portrait for a person: an arbitrary
    # OpenGraph thumbnail from a linked website cannot verify their identity.
    if page['group'] == 'Личности':
        return resolve(media.images[0], page) if media.images else ''
    if media.images:
        return resolve(media.images[0], page)
    for url in media.links:
        data = previews.get(url, {})
        image = data.get('local_image') or data.get('image')
        if image and safe_url(image):
            return image
    return resolve(media.images[0], page) if media.images else ''


def record_meta(group, row):
    if group == 'Личности':
        return ' — '.join(row.get(k,'') for k in ('Год рождения','Год смерти') if row.get(k,''))
    return re.sub(r' \(%.*$', '', row.get('Автор','') or row.get('Блок',''))


def records(group):
    return sorted(ordered[group], key=lambda page: page['title'].casefold()) if group == 'Темы' else ordered[group]


def gallery(group):
    markup = '<div class="cards' + (' quote-cards' if group == 'Цитаты' else '') + '">'
    for page in records(group):
        description = record_meta(group, rows_by_id[page['id']])
        image = page_image(page) if group not in ('Цитаты', 'Темы') else ''
        cover = (image_html(image, 'card-cover', '(max-width: 650px) 50vw, 320px') if image else
                 '<span class="card-etching" aria-hidden="true"></span>' if group == 'Темы' else '')
        markup += f'<a class="card" href="{page["id"]}.html">{cover}<span>{escape(page["title"])}</span>' + (f'<small>{escape(description)}</small>' if description else '') + '</a>'
    return markup + '</div>'


def record_list(group):
    markup = '<ul class="entry-list' + (' quotes-list' if group == 'Цитаты' else '') + '">'
    for page in records(group):
        description = record_meta(group, rows_by_id[page['id']])
        markup += f'<li><a class="entry-link" href="{page["id"]}.html"><span class="entry-title">{escape(page["title"])}</span>' + (f'<span class="entry-meta">{escape(description)}</span>' if description else '') + '</a></li>'
    return markup + '</ul>'


def database_table(group):
    columns = (['Name','Темы','Личности'] if group == 'История философии' else
               ['Name','Год рождения','Год смерти','Темы','История философии'] if group == 'Личности' else
               ['Name','Автор'] if group == 'Цитаты' else
               ['Name','История философии','Личности','Связь'] if group == 'Темы' else ['Name','Блок','Зачтено'])
    columns = [column for column in columns if column == 'Name' or any(row.get(column, '').strip() for row in databases[group])]
    markup = '<div class="table-scroll" tabindex="0" role="region" aria-label="'+escape(group)+'"><table class="database"><thead><tr>'
    markup += ''.join(f'<th scope="col"><button class="column-sort" type="button" data-column="{i}">{escape("Название" if column=="Name" else column)}</button></th>' for i,column in enumerate(columns)) + '</tr></thead><tbody>'
    for page in records(group):
        row = rows_by_id[page['id']]
        markup += '<tr><td><a href="'+page['id']+'.html">'+escape(page['title'])+'</a></td>' + ''.join('<td>'+property_html(row.get(column,''),page)+'</td>' for column in columns[1:]) + '</tr>'
    return markup + '</tbody></table></div>'


DEFAULT_VIEWS = {'Темы':'gallery','История философии':'table','Цитаты':'list','Личности':'table'}
for section_number, (group,label) in enumerate(GROUPS, start=1):
    dbid = next(i for i,name in db_ids.items() if name==group)
    body += (f'<section id="{dbid}" class="reference-section" aria-labelledby="heading-{dbid}">'
             f'<div class="section-heading"><h2 id="heading-{dbid}">{escape(label)}</h2></div>')
    default = DEFAULT_VIEWS[group]
    body += '<div class="view-controls" role="group" aria-label="Вид раздела">' + ''.join(f'<button type="button" data-view="{view}" aria-pressed="{str(view==default).lower()}">{view_label}</button>' for view,view_label in [('gallery','Галерея'),('list','Список'),('table','Таблица')]) + '</div>'
    for view,content in [('gallery',gallery(group)),('list',record_list(group)),('table',database_table(group))]:
        hidden = '' if view == default else ' hidden'
        body += f'<div data-view-content="{view}"{hidden}>{content}</div>'
    body += '</section>'
(OUT / 'index.html').write_text(shell('Философия',body,hero_quote=quote_html),encoding='utf-8')
search = [dict(title=p['title'],group=p['group'],url=('index.html' if p==home else p['id']+'.html'),text=re.sub(r'^Конспект:.*(?:\n|$)', '', p['text'], flags=re.MULTILINE)) for p in pages.values() if p['group'] != 'Самостоятельная работа']
(OUT / 'search.json').write_text(json.dumps(search,ensure_ascii=False),encoding='utf-8')
# List only canonical URLs, never query-string theme previews.
sitemap = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
for path in [''] + sorted(p['id'] + '.html' for p in pages.values() if p != home):
    entry = ET.SubElement(sitemap, 'url')
    ET.SubElement(entry, 'loc').text = SITE_URL + path
ET.ElementTree(sitemap).write(OUT / 'sitemap.xml', encoding='utf-8', xml_declaration=True)
(OUT / 'robots.txt').write_text(
    'User-agent: *\nAllow: /\nSitemap: ' + SITE_URL + 'sitemap.xml\n',
    encoding='utf-8'
)
print(f'Built {len(pages)} pages; {len(assets)} assets; '+', '.join(f'{g}: {len(ordered[g])}' for g,_ in GROUPS))
