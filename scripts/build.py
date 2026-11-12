"""Build a portable static reference from the original Notion export."""
import csv
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser
import markdown

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / 'content' / 'notion'
OUT = ROOT / 'dist'
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
THEME_BUTTON = ('<button id="theme-toggle" class="theme-toggle" type="button" aria-pressed="false" '
                'aria-label="Переключить цветовую тему"><span aria-hidden="true">◐</span>'
                '<span class="theme-label">Светлая тема</span></button>')
# CC0 photos of classical sculpture from Wikimedia Commons; not portraits of
# the named concepts, and never used to claim a historical identification.
COMMONS_THUMB = 'https://upload.wikimedia.org/wikipedia/commons/thumb/'
EDITORIAL_ART = {
    'hero': (
        COMMONS_THUMB + 'd/d4/Marble_Bust_of_Marcus_Aurelius_(Roman_Emperor_161-180_AD)_(28273837396).jpg/'
        '960px-Marble_Bust_of_Marcus_Aurelius_(Roman_Emperor_161-180_AD)_(28273837396).jpg',
        'https://commons.wikimedia.org/wiki/File:Marble_Bust_of_Marcus_Aurelius_(Roman_Emperor_161-180_AD)_(28273837396).jpg',
    ),
    'Онтология': (
        COMMONS_THUMB + '2/24/Roman_Marble_Statue_Head_(28204833482).jpg/'
        '960px-Roman_Marble_Statue_Head_(28204833482).jpg',
        'https://commons.wikimedia.org/wiki/File:Roman_Marble_Statue_Head_(28204833482).jpg',
    ),
    'Стоицизм': (
        'https://upload.wikimedia.org/wikipedia/commons/b/b3/Aristotle_bust.jpg',
        'https://commons.wikimedia.org/wiki/File:Aristotle_bust.jpg',
    ),
    'Эстетика': (
        COMMONS_THUMB + '7/7b/Ancient_Greece_Marble_Relief_Fragment_of_Female_Head%2C_Probably_Aphrodite%2C_from_Melos%2C_c._460-450_BC.jpg/'
        '500px-Ancient_Greece_Marble_Relief_Fragment_of_Female_Head%2C_Probably_Aphrodite%2C_from_Melos%2C_c._460-450_BC.jpg',
        'https://commons.wikimedia.org/wiki/File:Ancient_Greece_Marble_Relief_Fragment_of_Female_Head%2C_Probably_Aphrodite%2C_from_Melos%2C_c._460-450_BC.jpg',
    ),
    'Экзистенциализм': (
        COMMONS_THUMB + '8/8d/Ancient_Greece_Marble_Statue_Head_(28384794702).jpg/'
        '500px-Ancient_Greece_Marble_Statue_Head_(28384794702).jpg',
        'https://commons.wikimedia.org/wiki/File:Ancient_Greece_Marble_Statue_Head_(28384794702).jpg',
    ),
    'Герменевтика': (
        COMMONS_THUMB + 'c/ce/Marble_Herm_of_Plato_from_the_Academy%2C_3rd_C._AD%2C_Roman_Copy_of_Original_of_340_BC_which_was_Oldest_Displayed_Portrait_of_Plato_(28117624014).jpg/'
        '500px-Marble_Herm_of_Plato_from_the_Academy%2C_3rd_C._AD%2C_Roman_Copy_of_Original_of_340_BC_which_was_Oldest_Displayed_Portrait_of_Plato_(28117624014).jpg',
        'https://commons.wikimedia.org/wiki/File:Marble_Herm_of_Plato_from_the_Academy%2C_3rd_C._AD%2C_Roman_Copy_of_Original_of_340_BC_which_was_Oldest_Displayed_Portrait_of_Plato_(28117624014).jpg',
    ),
}

def shell(title, body, group=''):
    search_button = ('<button id="search-open" class="museum-search" type="button" '
                     'aria-label="Открыть поиск по справочнику" aria-haspopup="dialog" '
                     'aria-controls="search-dialog"><span aria-hidden="true">⌕</span></button>')
    search_action = (f'<div class="detail-masthead site-container">'
                     f'<a class="detail-brand" href="index.html" aria-label="PhiloLoom — на главную">PhiloLoom</a>'
                     f'<div class="detail-actions">{search_button}{THEME_BUTTON}</div></div>') if group else ''
    menu = ''.join(
        f'<a href="index.html#{next(i for i,n in db_ids.items() if n==group_name)}">{escape(menu_label)}</a>'
        for group_name, menu_label in [
            ('Темы', 'Темы'),
            ('История философии', 'История'),
            ('Личности', 'Мыслители'),
            ('Цитаты', 'Цитаты'),
        ]
    )
    shortcuts = ''.join(
        f'<a href="index.html#{next(i for i,n in db_ids.items() if n==group_name)}">'
        f'<strong>{escape(label)}</strong><small>{escape(description)}</small>'
        f'<span aria-hidden="true">↗</span></a>'
        for group_name, label, description in [
            ('История философии', 'История философии', 'Эпохи, школы, ключевые фигуры'),
            ('Темы', 'Философские темы', 'Понятия, направления, идеи'),
            ('Личности', 'Мыслители', 'Биографии, труды, связи'),
            ('Цитаты', 'Цитаты', 'Высказывания и авторы'),
        ]
    )
    hero_image, hero_source = EDITORIAL_ART['hero']
    cover = (f'<div class="museum-stage"><div class="museum-frame">'
             f'<div class="museum-head">'
             f'<a class="museum-wordmark" href="index.html" aria-label="PhiloLoom — на главную">PHILOLOOM</a>'
             f'<nav class="museum-top-nav" aria-label="Навигация по справочнику">{menu}'
             f'<a href="https://flsf.maxdudin.ru/" target="_blank" rel="noopener noreferrer">Статьи</a>'
             f'<a href="#about-philoloom">О проекте</a></nav>'
             f'<div class="museum-actions"><a class="museum-mobile-nav" href="#museum-shortcuts">Разделы</a>'
             f'{search_button}{THEME_BUTTON}</div></div>'
             f'<div class="hero-cover">'
             f'<div class="hero-artwork"><img src="{escape(hero_image, quote=True)}" '
             f'alt="Мраморный бюст Марка Аврелия" width="640" height="960" '
             f'fetchpriority="high" decoding="async"></div>'
             f'<div class="hero-orbit" aria-hidden="true"></div>'
             f'<div class="hero-cover-content">'
             f'<p class="hero-overline">Публичный философский справочник</p>'
             f'<h1>Философия <em>как искусство</em> мышления</h1>'
             f'<span class="hero-divider" aria-hidden="true"></span>'
             f'<p class="hero-summary">Идеи, мыслители, тексты и контексты — '
             f'пространство для исследования философии.</p>'
             f'<a class="hero-explore" href="#reference-nav">Перейти к темам '
             f'<span aria-hidden="true">⟶</span></a></div>'
             f'<p class="hero-credit">Мраморный бюст Марка Аврелия · '
             f'<a href="{escape(hero_source, quote=True)}" target="_blank" rel="noopener noreferrer">'
             f'Wikimedia Commons</a> · <a href="https://creativecommons.org/publicdomain/zero/1.0/" '
             f'target="_blank" rel="noopener noreferrer">CC0</a></p></div>'
             f'<nav id="museum-shortcuts" class="museum-shortcuts" aria-label="Основные направления">'
             f'{shortcuts}</nav></div></div>') if not group else ''
    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="theme-color" content="#0f0f0f">
<title>{escape(title)} · PhiloLoom</title>
<meta name="description" content="{escape(title, quote=True)} — история философии, направления и мыслители в справочнике PhiloLoom.">
<script>try{{document.documentElement.dataset.theme=localStorage.getItem('philoloom:theme')==='light'?'light':'dark'}}catch(e){{document.documentElement.dataset.theme='dark'}}</script>
<link rel="stylesheet" href="style.css">
<script src="app.js" defer></script>
</head>
<body>
<a class="skip" href="#main">К содержимому</a>
{search_action}<main id="main" class="{'home-page' if not group else 'detail-page'}">{cover + '<div class="site-container home-inner">' + body + '</div>' if not group else body}</main>
<footer><div class="site-container">PhiloLoom · Философский справочник · Автор: <a href="https://mksddn.ru/" target="_blank" rel="author noopener noreferrer">Макс Дудин</a></div></footer>
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
    return (f'<nav class="back page-breadcrumbs" aria-label="Путь по справочнику"><a href="index.html">PhiloLoom</a>'
            f'<span aria-hidden="true">/</span>{group_link}<span aria-hidden="true">/</span>'
            f'<span aria-current="page" title="{escape(page["title"],quote=True)}">{escape(page["title"])}</span></nav>')


READING_CONTROLS = ('<div class="reading-controls"><button type="button" data-reader-toggle aria-pressed="false">Режим чтения</button>'
                    '<div class="reader-options" hidden><span>Размер текста</span>'
                    '<button type="button" data-font-step="-1" aria-label="Уменьшить размер текста">A-</button>'
                    '<output data-reader-output aria-label="Размер текста">18 px</output>'
                    '<button type="button" data-font-step="1" aria-label="Увеличить размер текста">A+</button>'
                    '<label>Ширина <select data-reader-width><option value="narrow">Узкая</option><option value="normal" selected>Обычная</option><option value="wide">Широкая</option></select></label>'
                    '</div></div>')


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
    body = f'{breadcrumbs(p)}<h1{quote_class}>{escape(p["title"])}</h1>{connections_html}{READING_CONTROLS}<article>{render(body_text,p)}</article>'
    (OUT / (p['id'] + '.html')).write_text(shell(p['title'],body,p['group']),encoding='utf-8')

# Landing content is drawn from the untouched Notion introduction.
intro = home['text'].split('\n## ')[0]
quote_source = intro.split('- Посмотреть', 1)[0].splitlines()[1:]
quote_lines = [line.strip() for line in quote_source if line.strip() and line.strip() != '>']
quote_text = next((re.sub(r'^>\s*|\*\*', '', line) for line in quote_lines if line.startswith('>')), '')
quote_author = next((line for line in quote_lines if not line.startswith('>')), '')
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
        # Labels come from the curated source; generic OG titles must not replace them.
        description = (meta.get('description') or '').strip()
        generic = ('Делитесь видео с близкими', 'Share your videos')
        if description.startswith(generic):
            description = ''
        description_html = f'<span class="resource-card-description">{escape(description[:155])}</span>' if description else ''
        cards.append(f'<li><a class="resource-card" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                     f'{media}<span class="resource-card-copy"><strong>{escape(label)}</strong>'
                     f'{description_html}<small>{escape(domain)}</small></span>'
                     f'<span class="resource-card-arrow" aria-hidden="true">↗</span></a></li>')
    return '<ul class="resource-cards">' + ''.join(cards) + '</ul>'

watch = intro.split('- Посмотреть', 1)[1].split('- 📗', 1)[0] if '- Посмотреть' in intro else ''
read = intro.split('- 📗', 1)[1].split('[Блог о философии]', 1)[0] if '- 📗' in intro else ''
blog = 'https://flsf.maxdudin.ru/'
# OG image is optional: the local metadata cache does not currently contain it.
blog_meta = previews.get(blog, {})
blog_image = blog_meta.get('local_image') or blog_meta.get('image') or ''
blog_media = (f'<span class="blog-image">{image_html(blog_image, "blog-cover")}</span>'
              if blog_image and safe_url(blog_image) else '')
resource_dialog = ('<dialog id="resource-dialog" aria-labelledby="resource-title">'
                   '<div class="resource-toolbar"><h2 id="resource-title">Материалы</h2><button type="button" id="resource-close" aria-label="Закрыть">×</button></div>'
                   f'<div id="resource-watch" class="resource-list" hidden>{resource_cards(watch)}</div>'
                   f'<div id="resource-read" class="resource-list" hidden>{resource_cards(read)}</div>'
                   '</dialog>')
# All editorial entry points target original, unchanged pages.
def topic_page(title):
    return next((p for p in ordered['Темы'] if p['title'] == title), None)


spotlight = topic_page('Антропоцентризм')
if spotlight is None:
    raise ValueError('The editorial spotlight requires the existing Антропоцентризм page')
spotlight_image, _ = EDITORIAL_ART['hero']
lead = (f'<div class="editorial-headline"><span>ПУТЕВОДИТЕЛЬ ПО ИДЕЯМ</span>'
        f'<p>Исследуйте философию</p></div>'
        f'<div class="editorial-lead"><a class="editorial-spotlight" href="{spotlight["id"]}.html">'
        f'<span class="editorial-spotlight-media"><img src="{escape(spotlight_image, quote=True)}" '
        f'alt="" width="640" height="960" loading="lazy" decoding="async"></span>'
        f'<span class="editorial-spotlight-copy"><small>ИЗБРАННАЯ ТЕМА</small>'
        f'<strong>{escape(spotlight["title"])}</strong>'
        f'<span>Человек и его восприятие как центр размышлений о мире.</span>'
        f'<span class="editorial-spotlight-arrow" aria-hidden="true">↗</span></span></a>'
        f'{quote_html}</div>')

topic_titles = ['Онтология', 'Эстетика', 'Стоицизм', 'Герменевтика', 'Экзистенциализм']
selected_topics = [topic_page(title) for title in topic_titles]
if any(page is None for page in selected_topics):
    raise ValueError('Editorial shelf requires five existing public topic pages')
topic_tiles = []
for page in selected_topics:
    cover_url, _ = EDITORIAL_ART[page['title']]
    topic_tiles.append(
        f'<a class="editorial-topic" href="{page["id"]}.html">'
        f'<img src="{escape(cover_url, quote=True)}" alt="" width="480" height="640" '
        f'loading="lazy" decoding="async">'
        f'<span class="editorial-topic-title">{escape(page["title"])}</span>'
        f'<span class="editorial-topic-line" aria-hidden="true"></span></a>'
    )
shelf = (f'<section class="editorial-shelf" aria-labelledby="shelf-heading">'
         f'<div class="editorial-kicker"><span>КОЛЛЕКЦИЯ / ТЕМЫ</span><h2 id="shelf-heading">'
         f'Начните с этих идей</h2></div>'
         f'<div class="editorial-topic-grid">{"".join(topic_tiles)}</div>'
         f'</section>')
resources = (f'<section class="editorial-resources" aria-labelledby="resources-heading">'
             f'<div class="editorial-kicker"><span>ИСТОЧНИКИ И МАТЕРИАЛЫ</span>'
             f'<h2 id="resources-heading">Продолжить исследование</h2></div>'
             f'<div class="hero-resources">'
             f'<button type="button" class="resource-trigger" data-resource-open="watch" '
             f'aria-haspopup="dialog" aria-controls="resource-dialog"><span>Смотреть</span>'
             f'<small>Видеоматериалы о философии</small><span aria-hidden="true">↗</span></button>'
             f'<button type="button" class="resource-trigger" data-resource-open="read" '
             f'aria-haspopup="dialog" aria-controls="resource-dialog"><span>Читать</span>'
             f'<small>Статьи, журналы и библиотеки</small><span aria-hidden="true">↗</span></button>'
             f'<a class="blog-feature" href="{blog}" target="_blank" rel="noopener noreferrer">'
             f'{blog_media}<span class="blog-feature-copy"><strong>Блог о философии</strong>'
             f'<small>Статьи об истории и разделах философии</small></span>'
             f'<span class="blog-arrow" aria-hidden="true">↗</span></a>'
             f'</div></section>')
nav = nav  # Keep the original section targets and complete static index.
body = (lead + shelf + resources
        + '<div class="catalog-intro" id="reference-nav">'
        '<span>СПРАВОЧНИК / ВСЕ МАТЕРИАЛЫ</span><h2>Каталог философии</h2></div>'
        + f'<nav class="section-nav" aria-label="Разделы">{nav}</nav>')

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
             f'<div class="section-heading"><span aria-hidden="true">{section_number:02d} / 04</span>'
             f'<h2 id="heading-{dbid}">{escape(label)}</h2></div>')
    default = DEFAULT_VIEWS[group]
    body += '<div class="view-controls" role="group" aria-label="Вид раздела">' + ''.join(f'<button type="button" data-view="{view}" aria-pressed="{str(view==default).lower()}">{view_label}</button>' for view,view_label in [('gallery','Галерея'),('list','Список'),('table','Таблица')]) + '</div>'
    for view,content in [('gallery',gallery(group)),('list',record_list(group)),('table',database_table(group))]:
        hidden = '' if view == default else ' hidden'
        body += f'<div data-view-content="{view}"{hidden}>{content}</div>'
    body += '</section>'
body += ('<section id="about-philoloom" class="editorial-about" aria-labelledby="about-heading">'
         '<span>О ПРОЕКТЕ</span><h2 id="about-heading">Пространство для философских идей</h2>'
         '<p>PhiloLoom — публичный справочник, в котором собраны философские темы, '
         'история мысли, личности и цитаты. Материалы связаны между собой и доступны '
         'для последовательного чтения и самостоятельного исследования.</p></section>')
(OUT / 'index.html').write_text(shell('Философия',body),encoding='utf-8')
search = [dict(title=p['title'],group=p['group'],url=('index.html' if p==home else p['id']+'.html'),text=re.sub(r'^Конспект:.*(?:\n|$)', '', p['text'], flags=re.MULTILINE)) for p in pages.values() if p['group'] != 'Самостоятельная работа']
(OUT / 'search.json').write_text(json.dumps(search,ensure_ascii=False),encoding='utf-8')
print(f'Built {len(pages)} pages; {len(assets)} assets; '+', '.join(f'{g}: {len(ordered[g])}' for g,_ in GROUPS))
