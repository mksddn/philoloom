"""Cache the 12 previously hotlinked philosopher portraits from Wikimedia Commons.

Run manually when internet is available, followed by scripts/optimize_images.py.
Normal site builds remain fully offline and deterministic.
"""
import io
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PEOPLE = ROOT / 'content/knowledge/Философия/Личности'
DEST = ROOT / 'content/previews/portraits'
CREDITS = ROOT / 'docs/PORTRAIT_SOURCES.md'
SLUGS = (
    'fridrih-vilgelm-iozef-shelling',
    'gerbert-markuze',
    'iogann-gotlib-fihte',
    'ivan-kireevskii',
    'karl-yaspers',
    'maks-sheler',
    'mishel-fuko',
    'pavel-florenskii',
    'petr-chaadaev',
    'seren-obe-kerkegor',
    'sergei-bulgakov',
    'slavoi-zhizhek',
)


def portrait_source(slug):
    body = (PEOPLE / (slug + '.md')).read_text(encoding='utf-8')
    found = re.search(r'!\[[^\]]*\]\((https?://[^)]+)\)', body)
    if not found:
        raise ValueError(f'{slug}: missing explicitly sourced portrait in Markdown')
    url = found.group(1)
    source = urlsplit(url)
    if (source.scheme != 'https' or source.netloc != 'upload.wikimedia.org'
            or not source.path.startswith('/wikipedia/commons/')):
        raise ValueError(f'{slug}: not a Wikimedia Commons HTTPS file: {url}')
    return url


def cache_portraits():
    DEST.mkdir(parents=True, exist_ok=True)
    credits = []
    for slug in SLUGS:
        url = portrait_source(slug)
        target = DEST / (slug + '.jpg')
        if not target.exists():
            request = Request(url, headers={
                'User-Agent': 'Philoloom/1.0 (philosophical atlas; Wikimedia attribution is preserved)',
                'Accept': 'image/jpeg,image/png,image/webp,image/*'
            })
            with urlopen(request, timeout=35) as response:
                if not response.headers.get_content_type().startswith('image/'):
                    raise ValueError(f'{slug}: not an image response')
                raw = response.read(15_000_001)
                if len(raw) > 15_000_000:
                    raise ValueError(f'{slug}: source image exceeds 15 MB')
            with Image.open(io.BytesIO(raw)) as opened:
                if getattr(opened, 'is_animated', False):
                    raise ValueError(f'{slug}: unexpected animation')
                picture = ImageOps.exif_transpose(opened).convert('RGB')
                if min(picture.size) < 160:
                    raise ValueError(f'{slug}: source too small: {picture.size}')
                picture.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                picture.save(target, 'JPEG', quality=88, optimize=True, progressive=True)
        with Image.open(target) as verified:
            verified.verify()
        name = unquote(url.split('/')[-1])
        commons = 'https://commons.wikimedia.org/wiki/File:' + quote(name.replace(' ', '_'), safe="()'!_-")
        credits.append(f'| {slug} | [Wikimedia Commons]({commons}) | content/previews/portraits/{slug}.jpg |')
        print(f'Cached {slug}: {target.stat().st_size:,} bytes')
    CREDITS.write_text(
        '# Источники портретов\n\n'
        'Оригинальные изображения опубликованы в Wikimedia Commons. '
        'Копии уменьшены до 1800 пикселей по большей стороне и конвертированы '
        'в JPEG; для публикации создаются адаптивные WebP. '
        'Авторство и условия лицензирования каждого изображения указаны '
        'на соответствующей странице файла. Лицензии остаются у правообладателей.\n\n'
        '| Личность | Страница изображения и лицензия | Локальная копия |\n'
        '| --- | --- | --- |\n' + '\n'.join(credits) + '\n',
        encoding='utf-8'
    )


if __name__ == '__main__':
    cache_portraits()
