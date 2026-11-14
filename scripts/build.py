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
# IDs remain the source of truth; the checked-in map pins stable public URLs.
SLUGS = json.loads((ROOT / 'content' / 'slugs.json').read_text(encoding='utf-8'))

def page_url(page):
    if page['id'] == home['id']:
        return 'index.html'
    if page['group'] == 'Цитаты':
        return 'index.html#quote-' + page['id']
    return SLUGS.get(page['id'], '#')

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


def image_html(url, css_class='', sizes='(max-width: 700px) 100vw, 700px', priority=False, alt=''):
    info = image_info(url)
    attrs = f' class="{escape(css_class, quote=True)}"' if css_class else ''
    attrs += f' alt="{escape(alt, quote=True)}"'
    if info:
        variants = info['variants']
        largest = variants[-1]
        srcset = ', '.join(f"{item['url']} {item['width']}w" for item in variants)
        attrs += (f' srcset="{escape(srcset,quote=True)}" sizes="{escape(sizes,quote=True)}"'
                  f' width="{largest["width"]}" height="{largest["height"]}" data-full-src="{largest["url"]}"')
        url = largest['url']
    loading = 'fetchpriority="high"' if priority else 'loading="lazy"'
    return f'<img{attrs} src="{escape(url,quote=True)}" {loading} decoding="async" referrerpolicy="no-referrer">'


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
            return page_url(pages[pid])
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

public_ids = {page['id'] for group, _ in GROUPS if group != 'Цитаты' for page in ordered[group]}
if set(SLUGS) != public_ids:
    raise ValueError('Public slug registry does not match the current published IDs. Update content/slugs.json.')
if len(set(SLUGS.values())) != len(SLUGS) or any(
    not re.fullmatch(r'(?:people|topics|history)/[a-z0-9]+(?:-[a-z0-9]+)*/', value)
    for value in SLUGS.values()
):
    raise ValueError('Duplicate or invalid public slugs.')

nav = (''.join(f'<a href="index.html#{next(i for i,n in db_ids.items() if n==g)}">{label}</a>' for g,label in GROUPS)
       + '<a href="index.html#more">Ещё</a>')

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


def shell(title, body, group='', hero_quote='', canonical_path='', extra_script=''):
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
{('<base href="../../">' if canonical_path.count('/') == 2 else '<base href="../">' if canonical_path == 'map/' else '')}
<title>{escape(title)} · philoloom</title>
<link rel="canonical" href="{escape(SITE_URL + canonical_path, quote=True)}">
<meta name="description" content="{escape("Интерактивная карта философских знаний Филолум. Исследуйте идеи, мыслителей и связи между ними." if not group else title + " — история философии, направления и мыслители в справочнике philoloom.", quote=True)}">
<script>const previewTheme = new URLSearchParams(location.search).get('theme'); document.documentElement.dataset.theme = ['light', 'dark'].includes(previewTheme) ? previewTheme : (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');</script>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<meta property="og:site_name" content="philoloom">
<link rel="stylesheet" href="style.css">
<script src="app.js" defer></script>
{extra_script}
</head>
<body>
<a class="skip" href="#main">К содержимому</a>
<main id="main" class="{'home-page' if not group else 'detail-page'}">{cover + '<div class="site-container home-inner">' + body + '</div>' if not group else body}</main>
<footer><div class="site-container"><span class="footer-brand"><span class="brand-accessible-name">philoloom</span><span class="footer-tree" aria-hidden="true"></span><span class="footer-wordmark" aria-hidden="true"></span></span><span class="footer-description"><a href="map/">Карта знаний</a> · Интерактивная карта философских знаний · Автор: <a href="https://mksddn.ru/" target="_blank" rel="author noopener noreferrer">Макс Дудин</a></span></div></footer>
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
for name in ('style.css', 'app.js', 'map.js'):
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


def referenced_ids(text):
    """IDs referenced in a source field or Markdown body, independent of order."""
    return set(re.findall(r'([a-f0-9]{32})\.md', unquote(text)))


def explicit_relations(page, relations, already_shown):
    """Show each explicit connection once, with labels specific to its context."""
    labels = {
        'Темы': {
            'История философии': 'Исторический контекст',
            'Личности': 'Философы',
            'Связь': 'Связанные темы',
            'Темы': 'Связанные темы',
        },
        'История философии': {
            'Личности': 'Представители',
            'Темы': 'Темы и направления',
            'Связь': 'Связанные разделы',
            'История философии': 'Исторический контекст',
        },
    }
    pattern = re.compile(r'([^\n]*?) \(([^\s]*?[a-f0-9]{32}\.md)\)(?:, |$)')
    rows = []
    for key, value in relations:
        links = []
        matches = list(pattern.finditer(value))
        for match in matches:
            pid_match = ID.search(unquote(match[2]))
            if not pid_match:
                continue
            pid = pid_match[1]
            # Private, unavailable and already visible records are not repeated.
            if pid not in public_ids or pid in already_shown:
                continue
            already_shown.add(pid)
            links.append(f'<a class="relation" href="{page_url(pages[pid])}">{escape(match[1].strip())}</a>')
        if not matches and value.strip():
            # Retain genuine free-form metadata, without inventing a relation.
            links.append(property_html(value, page))
        if links:
            label = labels.get(page['group'], {}).get(key, key)
            rows.append(f'<dt>{escape(label)}</dt><dd>{"".join(links)}</dd>')
    return '<dl class="properties entity-relations">' + ''.join(rows) + '</dl>' if rows else ''


def related_records(page, already_shown):
    """Discover incoming references that are not already visible in this page."""
    linked = sorted(
        (pages[pid] for pid in connections[page['id']]
         if pid in public_ids and pid not in already_shown),
        key=lambda p: (p['group'] != 'Темы', p['group'], p['title'].casefold()),
    )
    if not linked:
        return ''
    def items(records):
        return '<ul>' + ''.join(
            f'<li><a href="{page_url(p)}"><span>{escape(p["title"])}</span>'
            f'<small>{escape(p["group"])}</small></a></li>' for p in records
        ) + '</ul>'
    content = items(linked[:10])
    if len(linked) > 10:
        content += f'<details><summary>Ещё {len(linked)-10}</summary>{items(linked[10:])}</details>'
    heading = 'Где встречается эта тема' if page['group'] == 'Темы' else 'Где встречается этот раздел'
    return (f'<div class="discovered-links"><h3>{heading}</h3>'
            '<p>Ссылки из других материалов справочника.</p>' + content + '</div>')


QUOTE_PROVENANCE = json.loads((ROOT / 'content' / 'quote-provenance.json').read_text(encoding='utf-8'))['quotes']
QUOTE_STATUS_NOTES = {
    'source_located': 'Точность русского перевода не сверена',
    'paraphrase_review': 'Возможный пересказ, не дословная цитата',
    'unverified': 'Первоисточник не подтверждён',
}


def quote_figure(page, anchored=False):
    author = rows_by_id[page['id']].get('Автор', '')
    author_html = property_html(author, page) if author else 'Автор не указан'
    anchor = f' id="quote-{page["id"]}"' if anchored else ''
    info = QUOTE_PROVENANCE.get(page['id'])
    if not info:
        raise ValueError(f'No quotation provenance record for {page["id"]}')
    status = info.get('status')
    if status not in QUOTE_STATUS_NOTES:
        raise ValueError(f'Unexpected quotation review status for {page["id"]}: {status}')
    return (f'<figure class="quote-entry"{anchor}><span class="quote-entry-label">Цитата</span>'
            f'<blockquote><p>{escape(page["title"])}</p></blockquote>'
            f'<figcaption>{author_html}</figcaption></figure>')


def person_portrait(page):
    """Prefer cached Wikipedia preview for the explicitly illustrated person."""
    image_match = re.search(r'!\[[^\]]*\]\((https?://[^)]+)\)', page['text'])
    original = image_match[1] if image_match else ''
    if not original:
        return '', ''
    for url, metadata in previews.items():
        cached = metadata.get('local_image', '')
        if 'wikipedia.org/wiki/' in url and url in page['text'] and cached and image_info(cached):
            return cached, original
    # Never silently hotlink the portrait from Commons in the public UI.
    return '', original


def person_document(markdown_text):
    """Recompose existing Markdown visually; do not modify the original export."""
    lines, resources = [], []
    first_image_removed = False
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not first_image_removed and re.fullmatch(r'!\[[^\]]*\]\(https?://[^)]+\)', stripped):
            first_image_removed = True
            continue
        match = re.fullmatch(r'\[([^\]]+)\]\((https?://[^)]+)\)', stripped)
        if match and safe_url(match[2]):
            resources.append((match[1], match[2]))
            continue
        if stripped in ('Основные труды', 'Основные идеи'):
            lines.append('### ' + stripped)
        else:
            lines.append(line)
    return '\n'.join(lines).strip(), resources


def person_sources(resources, original):
    markup = []
    for label, url in resources:
        domain = urlsplit(url).netloc.removeprefix('www.')
        markup.append(f'<li><a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                      f'<span>{escape(label)}</span><small>{escape(domain)}</small></a></li>')
    if not markup and not original:
        return ''
    source_line = (
        f'<p class="person-image-source">Изображение: '
        f'<a href="{escape(original, quote=True)}" target="_blank" rel="noopener noreferrer">исходный файл</a></p>'
        if original else ''
    )
    return ('<section class="person-sources" aria-label="Дополнительные материалы">'
            '<h2>Дополнительные материалы</h2>'
            + ('<ul>' + ''.join(markup) + '</ul>' if markup else '')
            + source_line + '</section>')


def person_quotes(page):
    selected = [
        quote for quote in ordered['Цитаты']
        if page['id'] in re.findall(r'([a-f0-9]{32})\.md',
                                    unquote(rows_by_id[quote['id']].get('Автор', '')))
    ]
    if not selected:
        return ''
    tiles = ''.join(quote_figure(quote) for quote in selected)
    return ('<section class="person-quotes" aria-label="Высказывания в справочнике">'
            '<h2>Высказывания в справочнике</h2>'
            f'<div class="person-quote-grid">{tiles}</div>'
            '</section>')


def person_overview(page, facts_html, relations):
    picture, original = person_portrait(page)
    if picture:
        media = image_html(picture, 'person-portrait-image', '(max-width: 650px) 45vw, 260px',
                           alt=f'Иллюстрация: {page["title"]}')
    else:
        media = '<span class="person-portrait-placeholder" aria-hidden="true"></span>'
    portrait = f'<figure class="person-portrait">{media}</figure>'
    connection_html = (
        '<dl class="person-context">'
        + ''.join(f'<div><dt>{escape(k)}</dt><dd>{property_html(v,page)}</dd></div>' for k, v in relations)
        + '</dl>'
    ) if relations else ''
    return (f'<div class="person-overview">{portrait}<div class="person-overview-info">'
            f'{facts_html}{connection_html}</div></div>', original)


def breadcrumbs(page):
    group_id = next((pid for pid, group in db_ids.items() if group == page['group']), '')
    group_link = f'<a href="index.html#{group_id}">{escape(page["group"])}</a>' if group_id else ''
    return (f'<nav class="back page-breadcrumbs" aria-label="Путь по справочнику"><a href="index.html">philoloom</a>'
            f'<span aria-hidden="true">/</span>{group_link}<span aria-hidden="true">/</span>'
            f'<span aria-current="page" title="{escape(page["title"],quote=True)}">{escape(page["title"])}</span></nav>')



for p in pages.values():
    if p['id'] not in public_ids:
        continue
    props, body_text = page_parts(p)
    row = rows_by_id.get(p['id'])
    if row:
        props = [(k,v) for k,v in row.items() if k != 'Name']
    hidden_meta = {'Конспект', 'Задание', 'Зачтено', 'Моя работа', 'Связанные записи'}
    props = [(k,v) for k,v in props if v.strip() and k not in hidden_meta and not k.startswith('Самостоятельная работа')]

    # Short biographical facts accompany the identity. Relationships remain
    # an explicit part of the knowledge graph, never inferred from a portrait.
    fact_keys = {'Год рождения', 'Год смерти', 'Автор', 'Блок'}
    facts = [(k, v) for k, v in props if k in fact_keys]
    relations = [(k, v) for k, v in props if k not in fact_keys]
    facts_html = (
        '<section class="entity-facts" aria-label="Краткие сведения"><dl class="entity-facts-list">'
        + ''.join(f'<div class="entity-fact"><dt>{escape(k)}</dt><dd>{property_html(v,p)}</dd></div>'
                  for k, v in facts)
        + '</dl></section>'
    ) if facts else ''
    # People already show their relationships in the portrait overview and
    # their attributed quotations in a dedicated block: no generic footer.
    # For topics and history, source links shown in the article also count.
    connections_html = ''
    if p['group'] != 'Личности':
        shown = referenced_ids(body_text)
        shown.update(referenced_ids(' '.join(v for _, v in facts)))
        relation_list = explicit_relations(p, relations, shown)
        extra = related_records(p, shown)
        if relation_list or extra:
            title = '<h2 class="entity-links-title">Связанные материалы</h2>' if relation_list else ''
            connections_html = (
                '<section class="entity-links" aria-label="Связанные материалы">'
                f'{title}{relation_list}{extra}</section>'
            )
    kind = {'Темы': 'topics', 'Личности': 'people',
            'История философии': 'history'}.get(p['group'], 'other')
    head = (
        f'<div class="detail-navigation">{breadcrumbs(p)}{SEARCH_BUTTON}</div>'
        f'<div class="entity-detail entity-detail--{kind}">'
        f'<header class="entity-header"><span class="entity-kicker">{escape(p["group"])}</span>'
        f'<h1>{escape(p["title"])}</h1>'
        f'<a class="entity-map-link" href="map/?id={p["id"]}">На карте знаний</a></header>'
    )
    if p['group'] == 'Личности':
        overview, portrait_original = person_overview(p, facts_html, relations)
        readable_text, sources = person_document(body_text)
        text_html = (render(readable_text, p) if readable_text
                     else '<p class="person-no-essay">В этой записи пока нет развёрнутого очерка. '
                          'Связанные темы и дополнительные материалы помогут продолжить знакомство.</p>')
        body = (head + overview + f'<article>{text_html}</article>'
                + person_quotes(p) + person_sources(sources, portrait_original) + '</div>')
    else:
        body = head + facts_html + f'<article>{render(body_text,p)}</article>{connections_html}</div>'
    address = page_url(p)
    destination = OUT / address / 'index.html'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(shell(p['title'], body, p['group'], canonical_path=address), encoding='utf-8')

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
body = (f'<div class="catalog-toolbar"><nav id="reference-nav" class="section-nav" aria-label="Разделы">{nav}</nav>{SEARCH_BUTTON}</div>'
        '<p class="map-teaser"><a href="map/">Исследовать связи на карте знаний</a></p>')

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
    # Cached images derived from the linked Wikipedia page are available locally.
    # Never substitute unrelated link-preview art for a person's portrait.
    if page['group'] == 'Личности':
        return person_portrait(page)[0]
    if media.images:
        return resolve(media.images[0], page)
    for url in media.links:
        data = previews.get(url, {})
        image = data.get('local_image') or data.get('image')
        if image and safe_url(image):
            return image
    return ''


def record_meta(group, row):
    if group == 'Личности':
        return ' — '.join(row.get(k, '') for k in ('Год рождения', 'Год смерти') if row.get(k, ''))
    return re.sub(r' \(%.*$', '', row.get('Автор', '') or row.get('Блок', ''))


def death_sort_key(page):
    """Sort philosopher profiles by death, BCE first; undated people go last."""
    value = rows_by_id[page['id']].get('Год смерти', '').strip()
    match = re.search(r'-?\d{1,4}', value)
    if not match:
        return (1, 0, page['title'].casefold())
    year = int(match.group())
    if 'до н' in value.casefold() or 'bce' in value.casefold():
        year = -abs(year)
    return (0, year, page['title'].casefold())


def records(group):
    if group == 'Темы':
        return sorted(ordered[group], key=lambda page: page['title'].casefold())
    if group == 'Личности':
        return sorted(ordered[group], key=death_sort_key)
    return ordered[group]


# Each entity has one purposeful presentation. Relationships are taken directly
# from the original CSV: no previews, truncation, or artificial maximum counts.
CARD_RELATION_COLUMNS = {
    'Темы': ('История философии', 'Личности', 'Связь'),
    'История философии': ('Темы', 'Личности'),
    'Личности': ('Темы', 'История философии'),
}


def card_relationships(page):
    row = rows_by_id[page['id']]
    items = []
    for key in CARD_RELATION_COLUMNS[page['group']]:
        raw = row.get(key, '').strip()
        if raw:
            items.append(
                f'<div class="entity-card-connection">'
                f'<dt>{escape(key)}</dt><dd>{property_html(raw, page)}</dd></div>'
            )
    return ('<dl class="entity-card-connections">' + ''.join(items) + '</dl>') if items else ''


def entity_card(page):
    group = page['group']
    description = record_meta(group, rows_by_id[page['id']])
    media = ''
    if group == 'Личности':
        picture = page_image(page)
        media = (image_html(picture, 'card-cover', '(max-width: 650px) 50vw, 320px',
                            alt=f'Портрет: {page["title"]}') if picture else
                 '<span class="person-card-placeholder" aria-hidden="true"></span>')
        media = f'<span class="entity-card-media">{media}</span>'
    meta = f'<span class="entity-card-meta">{escape(description)}</span>' if description else ''
    kind = {'Темы': 'topics', 'История философии': 'history', 'Личности': 'people'}[group]
    return (f'<article class="entity-card entity-card--{kind}">'
            f'<a class="entity-card-main" href="{page_url(page)}">{media}'
            f'<span class="entity-card-title">{escape(page["title"])}</span>{meta}</a>'
            + card_relationships(page) + '</article>')


def cards_collection(group):
    return '<div class="entity-collection">' + ''.join(entity_card(p) for p in records(group)) + '</div>'


# The published history entries overlap in time: Russian philosophy covers
# several eras, so it is presented as a cross-period tradition, not assigned
# an arbitrary date or an invented place on a strict chronology.
# Approximate period boundaries intentionally overlap: historical schools and
# epochs are not mutually exclusive. These are navigation aids, not source facts.
HISTORY_PERIODS = {
    'antichnaya-filosofiya': 'ок. VI в. до н. э. — V в. н. э.',
    'srednevekovaya-filosofiya': 'ок. V–XV вв.',
    'filosofiya-novogo-vremeni-epoha-vozrozhdeniya': 'ок. XV–XVIII вв.',
    'nemetskii-idealizm': 'ок. 1780–1840 гг.',
    'filosofiya-xix-veka': 'XIX век (1801–1900)',
    'pervaya-polovina-xx-veka': '1901–1950 гг.',
    'vtoraya-polovina-hh-veka': '1951–2000 гг.',
    'filosofiya-xxi-veka': 'с 2001 года',
}
HISTORY_SEQUENCE = tuple(HISTORY_PERIODS)


def history_collection():
    entries = records('История философии')
    def slug(page):
        return page_url(page).rstrip('/').rsplit('/', 1)[-1]
    main = [p for p in entries if slug(p) in HISTORY_SEQUENCE]
    main.sort(key=lambda p: HISTORY_SEQUENCE.index(slug(p)))
    other = [p for p in entries if slug(p) not in HISTORY_SEQUENCE]
    content = ('<div class="history-timeline" aria-label="Исторические периоды">'
               + ''.join(
                   f'<div class="history-timeline-step">'
                   f'<span class="history-timeline-period" title="Ориентировочные даты">'
                   f'{escape(HISTORY_PERIODS[slug(p)])}</span>'
                   f'{entity_card(p)}</div>' for p in main
               ) + '</div>')
    if other:
        content += ('<div class="history-related"><h3>Сквозные традиции и разделы</h3>'
                    '<div class="entity-collection">' + ''.join(entity_card(p) for p in other)
                    + '</div></div>')
    return content


def quotes_collection():
    return ('<div class="quote-catalog">' +
            ''.join(quote_figure(p, anchored=True) for p in records('Цитаты')) +
            '</div>')


for group, label in GROUPS:
    dbid = next(i for i, name in db_ids.items() if name == group)
    body += (f'<section id="{dbid}" class="reference-section" aria-labelledby="heading-{dbid}">'
             f'<div class="section-heading"><h2 id="heading-{dbid}">{escape(label)}</h2></div>')
    body += (quotes_collection() if group == 'Цитаты' else
             history_collection() if group == 'История философии' else
             cards_collection(group))
    body += '</section>'

body += ('<section id="more" class="reference-section" aria-labelledby="heading-more">'
         '<div class="section-heading"><h2 id="heading-more">Ещё</h2></div>'
         + resources + '</section>')

(OUT / 'index.html').write_text(shell('Атлас философской мысли', body, hero_quote=quote_html), encoding='utf-8')


# Graph relations reflect links in the editorial corpus, not inferred ideas.
relation_fields = {'Темы', 'Личности', 'История философии', 'Связь', 'Представители'}
declared_pairs = set()
for pid in public_ids:
    for key in relation_fields:
        for target in referenced_ids(rows_by_id[pid].get(key, '')):
            if target in public_ids and target != pid:
                declared_pairs.add(tuple(sorted((pid, target))))
graph_nodes = [
    {'id': p['id'], 'title': p['title'], 'group': p['group'], 'url': page_url(p)}
    for p in sorted((pages[pid] for pid in public_ids),
                    key=lambda p: (p['group'], p['title'].casefold()))
]
pairs = sorted({
    tuple(sorted((pid, related)))
    for pid in public_ids for related in connections[pid]
    if related in public_ids and pid != related
})
graph_edges = [{'source': source, 'target': target,
                'kind': 'relation' if (source, target) in declared_pairs else 'mention'}
               for source, target in pairs]
(OUT / 'graph.json').write_text(json.dumps({
    'version': 1, 'notes': 'Explicit CSV relations and Markdown mentions only.',
    'nodes': graph_nodes, 'edges': graph_edges
}, ensure_ascii=False), encoding='utf-8')
degree = {node['id']: 0 for node in graph_nodes}
for edge in graph_edges:
    degree[edge['source']] += 1
    degree[edge['target']] += 1
hub_nodes = sorted(graph_nodes, key=lambda n: (-degree[n['id']], n['title']))[:20]
fallback = ''.join(
    f'<li><a href="{escape(n["url"],quote=True)}">{escape(n["title"])}</a></li>'
    for n in hub_nodes
)
map_body = (
    '<div class="site-container knowledge-page">'
    '<nav class="map-breadcrumb"><a href="index.html">Атлас философской мысли</a> / Карта знаний</nav>'
    '<header class="knowledge-header"><span class="entity-kicker">Исследование связей</span>'
    '<h1>Карта философских знаний</h1>'
    '<p>Выберите идею или мыслителя, чтобы увидеть связанные записи. Линия отражает'
    ' ссылку в справочнике, а не обязательно философское влияние или согласие.</p></header>'
    '<form id="graph-form" class="map-controls">'
    '<label for="graph-query">Найти запись</label>'
    '<input type="search" id="graph-query" list="graph-suggestions"'
    ' placeholder="Например, Онтология" required>'
    '<datalist id="graph-suggestions"></datalist><button type="submit">Показать</button>'
    '<label for="graph-group">Раздел</label>'
    '<select id="graph-group"><option value="">Все разделы</option>'
    '<option value="Темы">Темы</option><option value="Личности">Личности</option>'
    '<option value="История философии">История философии</option></select></form>'
    '<p id="graph-status" role="status" aria-live="polite">Загрузка карты…</p>'
    '<div class="map-layout"><div class="map-canvas">'
    '<svg id="graph-svg" viewBox="0 0 1000 660" role="img"'
    ' aria-label="Связи выбранной записи">'
    '<title>Карта знаний</title><desc>Все соседние записи также доступны списком.</desc></svg>'
    '</div><aside class="map-neighbors" aria-labelledby="graph-heading">'
    '<h2 id="graph-heading">Связанные материалы</h2>'
    '<p id="graph-detail"></p><ul id="graph-list"></ul></aside></div>'
    '<noscript><p>Без JavaScript доступны наиболее связанные записи:</p>'
    '<ul>' + fallback + '</ul></noscript></div>'
)
(OUT / 'map').mkdir(exist_ok=True)
(OUT / 'map' / 'index.html').write_text(
    shell('Карта философских знаний', map_body, 'Карта знаний',
          canonical_path='map/', extra_script='<script src="map.js" defer></script>'),
    encoding='utf-8'
)

search = [
    dict(title=p['title'], group=p['group'], url=page_url(p),
         text=re.sub(r'^Конспект:.*(?:\n|$)', '', p['text'], flags=re.MULTILINE))
    for p in pages.values() if p['id'] in public_ids or (p['group'] == 'Цитаты' and p['id'] in rows_by_id)
]
(OUT / 'search.json').write_text(json.dumps(search, ensure_ascii=False), encoding='utf-8')

# Old Notion-ID URLs remain as noindex HTML forwarding pages. GitHub Pages
# cannot produce real HTTP 301 redirects on its own; never list aliases
# in the sitemap or point canonical URLs back to the aliases.
def write_legacy_alias(page, destination):
    title = escape(page['title'])
    href = escape(destination, quote=True)
    canonical = escape(SITE_URL + destination.split('#', 1)[0], quote=True)
    markup = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
              f'<meta name="robots" content="noindex,follow">'
              f'<link rel="canonical" href="{canonical}">'
              f'<meta http-equiv="refresh" content="0;url={href}">'
              f'<title>{title} · philoloom</title></head>'
              f'<body><p>Страница переехала: <a href="{href}">{title}</a></p></body></html>')
    (OUT / (page['id'] + '.html')).write_text(markup, encoding='utf-8')


for page in pages.values():
    if page['id'] in public_ids or page['group'] == 'Цитаты' and page['id'] in rows_by_id:
        write_legacy_alias(page, page_url(page))

# Explicit legacy redirects for merged or renamed public records.
# These supplement the automatic Notion-ID forwarding pages.
LEGACY_REDIRECTS = json.loads((ROOT / 'content' / 'redirects.json').read_text(encoding='utf-8'))
for alias, target in LEGACY_REDIRECTS.items():
    if target not in SLUGS.values():
        raise ValueError(f'Legacy redirect target is not published: {target}')
    if not (re.fullmatch(r'[a-f0-9]{32}\.html', alias)
            or re.fullmatch(r'(?:topics|people|history)/[a-z0-9-]+/', alias)):
        raise ValueError(f'Invalid legacy redirect source: {alias}')
    destination = OUT / alias
    if alias.endswith('/'):
        destination = destination / 'index.html'
    if destination.exists():
        raise ValueError(f'Legacy redirect conflicts with an existing page: {alias}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    canonical_url = SITE_URL + target
    title = next(p['title'] for p in pages.values()
                 if SLUGS.get(p['id']) == target)
    destination.write_text(
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex,follow">'
        f'<link rel="canonical" href="{escape(canonical_url, quote=True)}">'
        f'<meta http-equiv="refresh" content="0;url={escape(canonical_url, quote=True)}">'
        f'<title>{escape(title)} · philoloom</title></head>'
        f'<body><p>Страница переехала: <a href="{escape(canonical_url, quote=True)}">'
        f'{escape(title)}</a></p></body></html>', encoding='utf-8'
    )


# The sitemap includes only human-readable canonical pages and the homepage.
sitemap = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
for path in ['', 'map/'] + sorted(SLUGS.values()):
    entry = ET.SubElement(sitemap, 'url')
    ET.SubElement(entry, 'loc').text = SITE_URL + path
ET.ElementTree(sitemap).write(OUT / 'sitemap.xml', encoding='utf-8', xml_declaration=True)
(OUT / 'robots.txt').write_text(
    'User-agent: *\nAllow: /\nSitemap: ' + SITE_URL + 'sitemap.xml\n',
    encoding='utf-8'
)
print(f'Built {len(public_ids)} public pages, {len(ordered["Цитаты"])} inline quotations; '
      + ', '.join(f'{g}: {len(ordered[g])}' for g, _ in GROUPS))
