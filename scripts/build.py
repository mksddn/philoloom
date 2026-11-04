"""Build a portable static reference from the original Notion export."""
import csv
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
        return quote(assets[candidate])
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
    media = (f'<span class="bookmark-media"><img src="{escape(image,quote=True)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>'
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
    return escape(value) if value else '<span class="empty">Пусто</span>'

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
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)} · PhiloLoom</title><meta name="description" content="PhiloLoom — личный философский справочник"><link rel="stylesheet" href="style.css"><script src="app.js" defer></script></head><body><a class="skip" href="#main">К содержимому</a><header><a class="brand" href="index.html">📜 PhiloLoom</a>{crumb}<button id="search-open" type="button">Поиск</button></header><main id="main">{body}</main><footer>PhiloLoom · Философский справочник</footer><dialog id="page-panel" aria-label="Подробности страницы"><div class="panel-toolbar"><button id="panel-back" aria-label="Назад в панели">←</button><button id="panel-next" aria-label="Следующая запись">↓</button><a id="panel-full" data-full-page aria-label="Открыть на всю страницу" title="Открыть на всю страницу">↗</a><button id="panel-close" aria-label="Закрыть подробности">×</button></div><div id="panel-content" class="panel-content" aria-live="polite"></div></dialog><dialog id="image-dialog" aria-label="Просмотр изображения"><button id="image-close" aria-label="Закрыть изображение">×</button><img id="image-full" alt=""></dialog><dialog id="search-dialog"><form method="dialog"><label for="query">Поиск по справочнику</label><button aria-label="Закрыть поиск">×</button></form><input id="query" type="search" placeholder="Тема, философ или фрагмент текста…" autocomplete="off"><p id="search-status" role="status"></p><ul id="results"></ul></dialog></body></html>'''

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir()
if (ROOT / 'content' / 'previews').exists():
    shutil.copytree(ROOT / 'content' / 'previews', OUT / 'previews')
for source,dest in assets.items():
    target = OUT / dest
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
for name in ('style.css', 'app.js'):
    shutil.copyfile(ROOT / 'site' / name, OUT / name)

for p in pages.values():
    if p == home:
        continue
    lines = p['text'].splitlines()[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    props = []
    while lines and re.match(r'^[^#>\-*\[\n]{1,35}: ', lines[0]):
        props.append(lines.pop(0).split(': ', 1))
    row = rows_by_id.get(p['id'])
    if row:
        props = [(k,v) for k,v in row.items() if k != 'Name']
    table = '<dl class="properties">' + ''.join(f'<dt>{escape(k)}</dt><dd>{property_html(v,p)}</dd>' for k,v in props) + '</dl>' if props else ''
    body = f'<nav class="back"><a href="index.html">← Философия</a></nav><h1>{escape(p["title"])}</h1>{table}<article>{render(chr(10).join(lines),p)}</article>'
    (OUT / (p['id'] + '.html')).write_text(shell(p['title'],body,p['group']),encoding='utf-8')

intro = home['text'].split('\n## ')[0].splitlines()[1:]
intro_html = render('\n'.join(intro),home)
# The export represents Notion toggles as top-level list items.
intro_html = re.sub(r'<li>\s*<p>(Посмотреть|📗\s*Почитать)</p>([\s\S]*?)</li>',r'<li><details><summary>\1</summary>\2</details></li>',intro_html)
body = f'<div class="page-icon">📜</div><h1>Философия</h1><div class="intro">{intro_html}</div><nav class="section-nav" aria-label="Разделы">{nav}</nav>'
def gallery(group):
    markup = '<div class="cards">'
    records = sorted(ordered[group], key=lambda p: p['title'].casefold()) if group == 'Темы' else ordered[group]
    for p in records:
        row = rows_by_id[p['id']]
        desc = row.get('Автор','') or row.get('Блок','')
        author = re.sub(r' \(%.*$', '', desc)
        cover = ''
        if group in ('Самостоятельная работа', 'Личности'):
            external = re.search(r'\]\((https?://[^\s)]+)\)', p['text'])
            # Prefer the biography bookmark metadata over an obsolete portrait URL.
            urls = re.findall(r'(?<!!)\[[^\]]*\]\((https?://[^\s)]+)\)', p['text'])
            image = next(((previews[u].get('local_image') or previews[u]['image']) for u in urls if previews.get(u,{}).get('image')), '')
            if not image and group == 'Личности' and external:
                image = external[1]
            if image and safe_url(image):
                cover = f'<img class="card-cover" src="{escape(image,quote=True)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
        markup += f'<a class="card" href="{p["id"]}.html">{cover}<span>{escape(p["title"])}</span>' + (f'<small>{escape(author)}</small>' if author else '') + '</a>'
    return markup + '</div>'


def database_table(group):
    columns = (['Name','Темы','Личности'] if group == 'История философии' else
               ['Name','Год рождения','Год смерти','Темы','История философии'] if group == 'Личности' else ['Name','Блок','Зачтено'])
    markup = '<div class="table-scroll" tabindex="0" role="region" aria-label="'+escape(group)+'"><table class="database"><thead><tr>'
    markup += ''.join(f'<th><button class="column-sort" type="button" data-column="{i}">{escape(c)}</button></th>' for i,c in enumerate(columns)) + '</tr></thead><tbody>'
    for p in ordered[group]:
        row = rows_by_id[p['id']]
        markup += '<tr><td><a href="'+p['id']+'.html">'+escape(p['title'])+'</a></td>' + ''.join('<td>'+property_html(row.get(c,''),p)+'</td>' for c in columns[1:]) + '</tr>'
    return markup + '</tbody></table></div>'


for group,label in GROUPS:
    dbid = next(i for i,n in db_ids.items() if n==group)
    body += f'<section id="{dbid}"><h2>{label}</h2>'
    if group in ('История философии','Личности','Самостоятельная работа'):
        default = 'gallery' if group == 'Самостоятельная работа' else 'table'
        body += '<div class="view-controls" role="group" aria-label="Вид раздела">' + ''.join(f'<button type="button" data-view="{view}" aria-pressed="{str(view==default).lower()}">{label}</button>' for view,label in [('table','Таблица'),('gallery','Галерея')]) + '</div>'
        for view,content in [('table',database_table(group)),('gallery',gallery(group))]:
            hidden = '' if view == default else ' hidden'
            body += f'<div data-view-content="{view}"{hidden}>{content}</div>'
    else:
        body += gallery(group)
    body += '</section>'
(OUT / 'index.html').write_text(shell('Философия',body),encoding='utf-8')
search = [dict(title=p['title'],group=p['group'],url=('index.html' if p==home else p['id']+'.html'),text=p['text']) for p in pages.values()]
(OUT / 'search.json').write_text(json.dumps(search,ensure_ascii=False),encoding='utf-8')
print(f'Built {len(pages)} pages; {len(assets)} assets; '+', '.join(f'{g}: {len(ordered[g])}' for g,_ in GROUPS))
