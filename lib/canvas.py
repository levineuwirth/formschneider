"""What a model is given, and what is done to what it gives back.

For the ornament-only route the kept letter is drawn on a canvas of the
provider's size, inside the initial's block, and the model may draw
everywhere except the letter and a halo of `grow` units around it. Some
providers honor a mask only loosely, so the letter and its halo are put
back from the canvas afterwards, exactly as given, whatever the model did
there. Style references are EB Garamond Initials' letters, rendered here.
"""

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from glyph import glyph
from paths import Path
from raster import bare_svg, ink, rasterize


@dataclass(frozen=True)
class Layout:
    size: tuple[int, int]               # the canvas, in pixels
    block: tuple[int, int, int, int]    # the initial's block on it: x0, y0, x1, y1
    box: tuple[int, int]                # the block, in units


def layout(box: tuple[int, int], size: tuple[int, int]) -> Layout:
    """The block as large as the canvas allows, centered."""
    k = min(size[0] / box[0], size[1] / box[1])
    w, h = round(box[0] * k), round(box[1] * k)
    x0, y0 = (size[0] - w) // 2, (size[1] - h) // 2
    return Layout(size, (x0, y0, x0 + w, y0 + h), box)


def letter_canvas(path: Path, box: tuple[int, int], size: tuple[int, int],
                  grow: float) -> tuple[Image.Image, np.ndarray, Layout]:
    """The letter, black on white, on the canvas; and where a model may
    draw (True), which is everywhere but the letter and its halo."""
    lay = layout(box, size)
    x0, y0, x1, y1 = lay.block
    letter = rasterize(bare_svg(path, box), x1 - x0).resize((x1 - x0, y1 - y0))
    canvas = Image.new("L", size, 255)
    canvas.paste(letter, (x0, y0))
    px = grow * (x1 - x0) / box[0]
    kept = distance_transform_edt(~ink(canvas)) <= px
    return canvas, ~kept, lay


def put_back(output: Image.Image, canvas: Image.Image, editable: np.ndarray,
             lay: Layout) -> Image.Image:
    """The model's picture with the letter and halo restored from the canvas,
    cropped to the block, in gray."""
    out = output.convert("L")
    if out.size != canvas.size:
        canvas = canvas.resize(out.size, Image.Resampling.LANCZOS)
        editable = np.asarray(Image.fromarray(editable).resize(out.size, Image.Resampling.NEAREST))
    merged = np.where(editable, np.asarray(out), np.asarray(canvas)).astype(np.uint8)
    kx, ky = out.size[0] / lay.size[0], out.size[1] / lay.size[1]
    x0, y0, x1, y1 = lay.block
    return Image.fromarray(merged).crop((round(x0 * kx), round(y0 * ky),
                                         round(x1 * kx), round(y1 * ky)))


def references(font: str, letters: str, size: int = 1024) -> list[tuple[str, Image.Image]]:
    """Each letter's initial, black on white, centered on a square with a margin."""
    out = []
    for c in letters:
        path, box = glyph(font, c)
        pic = rasterize(bare_svg(path, box), round(size * 0.9 * box[0] / max(box)))
        sq = Image.new("L", (size, size), 255)
        sq.paste(pic, ((size - pic.width) // 2, (size - pic.height) // 2))
        out.append((c, sq))
    return out


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
