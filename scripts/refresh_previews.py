"""Refresh public bookmark metadata. Normal builds use the committed cache offline."""
import concurrent.futures
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import markdown

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'content' / 'link-previews.json'

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        url = values.get('href', '')
        if tag == 'a' and url.startswith(('https://', 'http://')):
            self.urls.add(url)

class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.data, self.in_title, self.title = {}, False, ''
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta':
            key = values.get('property', values.get('name', '')).lower()
            self.data.setdefault(key, values.get('content', '').strip())
        if tag == 'title':
            self.in_title = True
    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            self.title += data

parser = Links()
for path in (ROOT / 'content' / 'notion').rglob('*.md'):
    parser.feed(markdown.markdown(path.read_text(encoding='utf-8')))
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

# Only URLs explicitly present in the user's reference are requested.
def fetch(url):
    try:
        request = Request(url, headers={'User-Agent': 'PhiloLoom/1.0 (public link preview)'})
        with urlopen(request, timeout=8) as response:
            if 'html' not in response.headers.get('Content-Type', ''):
                return url, None
            encoding = response.headers.get_content_charset() or 'utf-8'
            document = response.read(1500000).decode(encoding, errors='replace')
            final_url = response.url
        meta = Metadata()
        meta.feed(document)
        image = meta.data.get('og:image') or meta.data.get('twitter:image', '')
        image = urljoin(final_url, image) if image else ''
        if urlsplit(image).netloc == 'i.ytimg.com':
            image = image.split('?')[0]
        if urlsplit(image).scheme not in ('http','https'):
            image = ''
        return url, dict(title=meta.data.get('og:title') or meta.title.strip(),
                         description=meta.data.get('og:description') or meta.data.get('description', ''), image=image)
    except Exception:
        return url, None

urls = sorted(parser.urls)
if '--missing' in sys.argv:
    urls = [u for u in urls if u not in cache]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    for url, result in executor.map(fetch, urls):
        if result and any(result.values()):
            previous = cache.get(url, {})
            if previous.get('image') != result.get('image'):
                previous = {key:value for key,value in previous.items() if key != 'local_image'}
            cache[url] = {**previous, **result}
CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')
print(f'Cached metadata for {len(cache)} of {len(parser.urls)} public links.')

if '--download-images' in sys.argv:
    import hashlib
    media_dir = ROOT / 'content' / 'previews'
    media_dir.mkdir(exist_ok=True)
    def download(item):
        url, metadata = item
        image = metadata.get('image', '')
        existing = metadata.get('local_image')
        if existing and (ROOT/'content'/existing).is_file():
            return
        if urlsplit(image).scheme not in ('http','https'):
            return
        try:
            request = Request(image, headers={'User-Agent':'PhiloLoom/1.0 (public link preview)'})
            with urlopen(request,timeout=10) as response:
                kind = response.headers.get_content_type()
                suffix = {'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif'}.get(kind)
                if not suffix:
                    return
                data = response.read(3000001)
                if len(data)>3000000:
                    return
            name = hashlib.sha256(image.encode()).hexdigest()[:24]+suffix
            (media_dir/name).write_bytes(data)
            metadata['local_image'] = 'previews/'+name
        except Exception:
            pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(download,cache.items()))
    CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'Cached {sum(bool(m.get("local_image")) for m in cache.values())} preview images.')
