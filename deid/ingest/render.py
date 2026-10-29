"""Draw a synthetic note onto a page image, with mild scan-like damage.

Needs Pillow (a test-data dependency only; the pipeline itself does not). The
damage is a slight rotation, blur and speckle, applied from a seed so the same
note always gives the same image.
"""

import random
from pathlib import Path

FONT_CANDIDATES = ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")


def _font(size):
    from PIL import ImageFont
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def wrap(text, font, width):
    lines = []
    for raw in text.split("\n"):
        line = ""
        for word in raw.split(" "):
            trial = f"{line} {word}" if line else word
            if line and font.getlength(trial) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def render_scan(text, path, seed=0, size=22, width=1100, damage=True):
    from PIL import Image, ImageDraw, ImageFilter
    rng = random.Random(seed)
    font = _font(size)
    margin, lead = 50, int(size * 1.45)
    lines = wrap(text, font, width - 2 * margin)
    image = Image.new("L", (width, 2 * margin + lead * len(lines)), 255)
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((margin, margin + i * lead), line, fill=20, font=font)
    if damage:
        image = image.rotate(rng.uniform(-0.6, 0.6), resample=Image.BICUBIC, fillcolor=255)
        image = image.filter(ImageFilter.GaussianBlur(0.5))
        pixels = image.load()
        for _ in range(width * image.height // 700):
            x, y = rng.randrange(image.width), rng.randrange(image.height)
            pixels[x, y] = rng.randrange(120, 200)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
