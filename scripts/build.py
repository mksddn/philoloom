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
GROUPS = [('Темы', '📌 Темы'), ('История философии', '🕰️ История философии'),
          ('Цитаты', '💬 Цитаты'), ('Личности', '🗂️ Личности'),
          ('Самостоятельная работа', '💪 Мои статьи')]
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
for group,_ in GROUPS:
    ordered[group] = []
    for row in databases[group]:
        p = matching_page(group, row)
        ordered[group].append(p)
        rows_by_id[p['id']] = row

nav = ''.join(f'<a href="index.html#{next(i for i,n in db_ids.items() if n==g)}">{label}</a>' for g,label in GROUPS)

def shell(title, body, group=''):
    crumb = f'<span>/</span><span>{escape(group)}</span>' if group else ''
    cover = f'<div class="hero-cover">{image_html("ui/forest-cover.jpg", sizes="100vw", priority=True)}</div>' if not group else ''
    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{escape(title)} · PhiloLoom</title>
<meta name="description" content="PhiloLoom — личный философский справочник">
<link rel="stylesheet" href="style.css">
<script src="app.js" defer>
</script>
</head>
<body>
<a class="skip" href="#main">К содержимому</a>
<header>
<a class="brand" href="index.html">📜 PhiloLoom</a>{crumb}<button id="search-open" type="button">Поиск</button>
</header>{cover}<main id="main" class="{'home-page' if not group else 'detail-page'}">{body}</main>
<footer>PhiloLoom · Философский справочник</footer>
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
<dialog id="search-dialog">
<form method="dialog">
<label for="query">Поиск по справочнику</label>
<button aria-label="Закрыть поиск">×</button>
</form>
<input id="query" type="search" placeholder="Тема, философ или фрагмент текста…" autocomplete="off">
<p id="search-status" role="status">
</p>
<ul id="results">
</ul>
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


def related_records(page):
    linked = sorted((pages[pid] for pid in connections[page['id']]), key=lambda p: (p['group'] != 'Темы', p['group'], p['title'].casefold()))
    if not linked:
        return ''
    def items(records):
        return '<ul>' + ''.join(f'<li><a href="{p["id"]}.html"><span>{escape(p["title"])}</span><small>{escape(p["group"])}</small></a></li>' for p in records) + '</ul>'
    content = items(linked[:10])
    if len(linked) > 10:
        content += f'<details><summary>Ещё {len(linked)-10}</summary>{items(linked[10:])}</details>'
    return '<aside class="related-records" aria-label="Связанные записи"><h2>Связанные записи</h2>' + content + '</aside>'


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
    props = [(k,v) for k,v in props if v.strip() and k != 'Конспект']
    table = '<dl class="properties">' + ''.join(f'<dt>{escape(k)}</dt><dd>{property_html(v,p)}</dd>' for k,v in props) + '</dl>' if props else ''
    quote_class = ' class="quote-heading"' if p['group'] == 'Цитаты' else ''
    body = f'{breadcrumbs(p)}<h1{quote_class}>{escape(p["title"])}</h1>{READING_CONTROLS}{table}<article>{render(body_text,p)}</article>{related_records(p)}'
    (OUT / (p['id'] + '.html')).write_text(shell(p['title'],body,p['group']),encoding='utf-8')

intro = home['text'].split('\n## ')[0].splitlines()[1:]
intro_html = render('\n'.join(intro),home)
# The export represents Notion toggles as top-level list items.
intro_html = re.sub(r'<li>\s*<p>(Посмотреть|📗\s*Почитать)</p>([\s\S]*?)</li>',r'<li><details><summary>\1</summary>\2</details></li>',intro_html)
body = f'<div class="page-icon">📜</div><h1>Философия</h1><div class="intro">{intro_html}</div><nav class="section-nav" aria-label="Разделы">{nav}</nav>'
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
    # Prefer saved portraits for people; preserve original embedded illustrations for articles.
    if page['group'] != 'Личности' and media.images:
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
        cover = image_html(image, 'card-cover', '(max-width: 650px) 50vw, 320px') if image else ''
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


DEFAULT_VIEWS = {'Темы':'gallery','История философии':'table','Цитаты':'list','Личности':'table','Самостоятельная работа':'gallery'}
for group,label in GROUPS:
    dbid = next(i for i,name in db_ids.items() if name==group)
    body += f'<section id="{dbid}" class="reference-section" aria-labelledby="heading-{dbid}"><h2 id="heading-{dbid}">{label}</h2>'
    default = DEFAULT_VIEWS[group]
    body += '<div class="view-controls" role="group" aria-label="Вид раздела">' + ''.join(f'<button type="button" data-view="{view}" aria-pressed="{str(view==default).lower()}">{view_label}</button>' for view,view_label in [('gallery','Галерея'),('list','Список'),('table','Таблица')]) + '</div>'
    for view,content in [('gallery',gallery(group)),('list',record_list(group)),('table',database_table(group))]:
        hidden = '' if view == default else ' hidden'
        body += f'<div data-view-content="{view}"{hidden}>{content}</div>'
    body += '</section>'
(OUT / 'index.html').write_text(shell('Философия',body),encoding='utf-8')
search = [dict(title=p['title'],group=p['group'],url=('index.html' if p==home else p['id']+'.html'),text=re.sub(r'^Конспект:.*(?:\n|$)', '', p['text'], flags=re.MULTILINE)) for p in pages.values()]
(OUT / 'search.json').write_text(json.dumps(search,ensure_ascii=False),encoding='utf-8')
print(f'Built {len(pages)} pages; {len(assets)} assets; '+', '.join(f'{g}: {len(ordered[g])}' for g,_ in GROUPS))
