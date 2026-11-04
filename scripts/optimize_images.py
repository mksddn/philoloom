"""Create deterministic responsive WebP assets without altering original images."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'content' / 'optimized'
MANIFEST = ROOT / 'content' / 'image-manifest.json'
SUFFIXES = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
VERSION = 'webp-v1-quality82-lossless-diagrams'


def optimize():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources = []
    for folder in ('content/notion', 'content/previews', 'site/assets'):
        sources.extend(p for p in (ROOT / folder).rglob('*') if p.suffix.lower() in SUFFIXES)
    previous = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    manifest = {'version': 1, 'encoder': VERSION, 'sources': {}}
    original_bytes = 0
    output_bytes = 0
    for source in sorted(sources):
        data = source.read_bytes()
        if data.startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise RuntimeError('Image contains a Git LFS pointer. Run git lfs pull before optimizing.')
        original_bytes += len(data)
        relative = source.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(data).hexdigest()
        cached = previous.get('sources', {}).get(relative)
        if previous.get('encoder') == VERSION and cached and cached['sha256'] == digest and all((OUTPUT / Path(v['url']).name).is_file() for v in cached['variants']):
            manifest['sources'][relative] = cached
            output_bytes += sum(v['bytes'] for v in cached['variants'])
            continue
        fingerprint = hashlib.sha256(data + VERSION.encode()).hexdigest()[:24]
        with Image.open(source) as opened:
            if getattr(opened, 'is_animated', False):
                raise ValueError(f'Animated image requires an animation-preserving encoder: {relative}')
            image = ImageOps.exif_transpose(opened).convert('RGBA' if 'A' in opened.getbands() or 'transparency' in opened.info else 'RGB')
        hero = relative == 'site/assets/forest-cover.jpg'
        diagram = relative.startswith('content/notion/')
        widths = [640, 1280, 1920] if hero else [640, 1280, image.width] if diagram else [320, 640, 960]
        variants = []
        for width in sorted({min(width, image.width) for width in widths}):
            height = max(1, round(image.height * width / image.width))
            resized = image.resize((width, height), Image.Resampling.LANCZOS)
            filename = f'{fingerprint}-{width}.webp'
            target = OUTPUT / filename
            if not target.exists():
                resized.save(target, 'WEBP', quality=82, method=6, lossless=diagram, exact=True)
            with Image.open(target) as check:
                check.verify()
            variants.append({'url': 'media/' + filename, 'width': width, 'height': height, 'bytes': target.stat().st_size})
            output_bytes += target.stat().st_size
        manifest['sources'][relative] = {'sha256': hashlib.sha256(data).hexdigest(),
                                       'original_bytes': len(data), 'variants': variants}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(f'Optimized {len(sources)} images: original {original_bytes:,} bytes; all responsive variants {output_bytes:,} bytes.')
    return manifest


if __name__ == '__main__':
    optimize()
