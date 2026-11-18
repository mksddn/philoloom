"""Render reliable, locally hosted 1200×630 JPEG share cards during the site build.

A raster JPEG is used for social crawlers even when the web UI displays
responsive WebP. Source portrait images and artwork already belong to the repo.
"""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE = (1200, 630)
BACKGROUND = '#0d1514'
TEXT = '#f3f2e9'
MUTED = '#c9d2c7'
ACCENT = '#9ebba9'
BRAND_ASSETS = Path(__file__).resolve().parents[1] / 'site' / 'assets'


@lru_cache(maxsize=1)
def _brand_images():
    """Reuse the approved tree emblem and vector wordmark across share cards."""
    with Image.open(BRAND_ASSETS / 'philoloom-tree.webp') as source:
        tree = source.convert('RGBA').resize((68, 68), Image.Resampling.LANCZOS)
    svg_png = cairosvg.svg2png(
        url=str(BRAND_ASSETS / 'philoloom-wordmark.svg'), output_width=296)
    with Image.open(BytesIO(svg_png)) as source:
        wordmark = source.convert('RGBA')
    return tree, wordmark



def _font(size, bold=False):
    family = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    try:
        return ImageFont.truetype(family, size)
    except OSError as exc:
        raise RuntimeError(f'A Cyrillic-capable font is needed for OG images: {family}') from exc


def _wrap(text, font, max_width, drawer):
    """Wrap to rendered pixel width; split unusually long words as a fallback."""
    lines = []
    current = ''
    for word in text.split():
        candidate = (current + ' ' + word).strip()
        if drawer.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        if drawer.textlength(word, font=font) <= max_width:
            current = word
            continue
        segment = ''
        for char in word:
            if segment and drawer.textlength(segment + char, font=font) > max_width:
                lines.append(segment)
                segment = char
            else:
                segment += char
        current = segment
    if current:
        lines.append(current)
    return lines


def render_social_image(destination, artwork, title, section, portrait=None):
    """Create one visual identity card; always JPEG, 1200×630, under 5 MB."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(artwork) as original:
        backdrop = ImageOps.fit(original.convert('RGB'), SIZE, method=Image.Resampling.LANCZOS,
                                centering=(0.5, 0.5))
    # The supplied hero art is a background, not a stand-in portrait.
    canvas = Image.blend(backdrop, Image.new('RGB', SIZE, BACKGROUND), 0.78)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 10, SIZE[1]), fill=ACCENT)
    # Use the real brand assets, including the custom infinity-shaped 'oo'.
    tree, wordmark = _brand_images()
    canvas.paste(tree, (70, 50), tree)
    canvas.paste(wordmark, (154, 50), wordmark)
    draw.text((72, 124), section.upper(), font=_font(23, bold=True), fill=ACCENT)
    draw.line((70, 548, 1130, 548), fill='#486458', width=2)
    draw.text((72, 564), 'Интерактивная карта философских знаний',
              font=_font(22), fill=MUTED)

    has_portrait = portrait is not None
    if has_portrait:
        frame = (794, 83, 1135, 515)
        frame_width, frame_height = frame[2] - frame[0], frame[3] - frame[1]
        with Image.open(portrait) as original:
            face = ImageOps.fit(original.convert('RGB'), (frame_width, frame_height),
                                method=Image.Resampling.LANCZOS, centering=(0.5, 0.3))
        mask = Image.new('L', (frame_width, frame_height), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, frame_width - 1, frame_height - 1),
                                                 radius=9, fill=255)
        canvas.paste(face, (frame[0], frame[1]), mask)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(frame, radius=9, outline='#b0c6b5', width=2)

    max_width = 680 if has_portrait else 1055
    lines = []
    title_font = None
    for size in range(72, 31, -2):
        font = _font(size, bold=True)
        candidate = _wrap(title, font, max_width, draw)
        line_height = round(size * 1.26)
        if len(candidate) * line_height <= 322:
            lines = candidate
            title_font = font
            break
    if not lines:
        raise ValueError(f'Social card title cannot fit: {title!r}')
    spacing = round(title_font.size * 1.26)
    y = 204 + max(0, (310 - len(lines) * spacing) // 2)
    for line in lines:
        draw.text((70, y), line, font=title_font, fill=TEXT)
        y += spacing

    canvas.save(destination, 'JPEG', quality=88, optimize=True, progressive=True)
    if destination.stat().st_size > 5_000_000:
        raise ValueError(f'OG preview exceeds 5 MB: {destination}')
    return destination
