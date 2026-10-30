"""What the bench hands the reader: a markdown table and a contact sheet."""

from PIL import Image, ImageDraw, ImageFont


def table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    """cols: (heading, format) pairs; the format is filled from the row."""
    out = ["| " + " | ".join(h for h, _ in cols) + " |",
           "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(f.format(**r) for _, f in cols) + " |")
    return "\n".join(out) + "\n"


def _font(size: int):
    try:  # Pillow's own face has no accents, and the idioms are French
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def contact(sheet: list[tuple[str, list[tuple[str, Image.Image]]]], cell: int = 300) -> Image.Image:
    """sheet: rows of (name, [(caption, picture)])."""
    pad, label = 12, 34
    cols = max(len(p) for _, p in sheet)
    img = Image.new("L", (cols * (cell + pad) + pad,
                          len(sheet) * (cell + label + pad) + pad), 255)
    draw, font = ImageDraw.Draw(img), _font(14)
    for r, (_, picks) in enumerate(sheet):
        for k, (caption, pic) in enumerate(picks):
            x, y = pad + k * (cell + pad), pad + r * (cell + label + pad)
            pic = pic.convert("L")
            pic.thumbnail((cell, cell))
            img.paste(pic, (x, y))
            draw.text((x, y + cell + 6), caption, fill=0, font=font)
    return img
