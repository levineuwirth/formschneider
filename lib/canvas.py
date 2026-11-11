"""What a model is given, and what is done to what it gives back.

For the ornament-only route the kept letter is drawn on a canvas of the
provider's size, inside the initial's block, and the model may draw
everywhere except the letter and a halo of `grow` units around it. Some
providers honor a mask only loosely, so the letter and its halo are put
back from the canvas afterwards, exactly as given, whatever the model did
there. Style references are EB Garamond Initials' letters, rendered here.
"""

import io
import math
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
                  grow: float, fill: bool = False) -> tuple[Image.Image, np.ndarray, Layout]:
    """The letter, black on white, on the canvas; and where a model may
    draw (True), which is everywhere but the letter and its halo, and with
    `fill` nowhere outside the block either, since that is cropped away."""
    lay = layout(box, size)
    x0, y0, x1, y1 = lay.block
    letter = rasterize(bare_svg(path, box), x1 - x0).resize((x1 - x0, y1 - y0))
    canvas = Image.new("L", size, 255)
    canvas.paste(letter, (x0, y0))
    px = grow * (x1 - x0) / box[0]
    editable = ~(distance_transform_edt(~ink(canvas)) <= px)
    if fill:
        inside = np.zeros_like(editable)
        inside[y0:y1, x0:x1] = True
        editable &= inside
    return canvas, editable, lay


def halo_view(canvas: Image.Image, editable: np.ndarray) -> Image.Image:
    """Where the model may draw, for the eye: white where it may, the letter
    black, and what is kept white but not the letter (the halo, and any
    margin outside the block) in red."""
    rgb = np.stack([np.asarray(canvas.convert("L"))] * 3, -1)
    rgb[~editable & (np.asarray(canvas.convert("L")) >= 128)] = (220, 60, 60)
    return Image.fromarray(rgb, "RGB")


def registration(output: Image.Image, canvas: Image.Image, lay: Layout, grow: float,
                 ring: float = 12, reach: float = 60) -> dict:
    """How the model's own picture of the letter sits on the kept one, read
    before the letter is put back, all on the canvas and in units:

    letter_iou  agreement of the model's ink with the letter over the letter
                and its halo, the region put back (1: drawn where it was)
    band        the share of a ring `ring` units wide just outside the halo
                that the model inked: a letter redrawn heavier or moved
                leaves this as a dark band once the kept letter is put back
    drift       how far the model's ink best matches the letter shifted, at
                most `reach` units: a letter the model moved
    stretch     how far the picture's shape is from the canvas's, as a share,
                for a model that chose its own size"""
    from prepare import otsu
    out = output.convert("L")
    stretch = abs(math.log(out.width / out.height * canvas.height / canvas.width))
    if out.size != canvas.size:
        out = out.resize(canvas.size, Image.Resampling.LANCZOS)
    drawn = np.asarray(out) <= round(otsu(out) * 255)
    letter = ink(canvas)
    x0, y0, x1, y1 = lay.block
    ppu = (x1 - x0) / lay.box[0]
    inside = np.zeros_like(letter)
    inside[y0:y1, x0:x1] = True
    dist = distance_transform_edt(~letter)
    halo = grow * ppu
    zone = letter | (dist <= halo)
    rim = inside & (dist > halo) & (dist <= halo + ring * ppu)
    near = inside & (dist <= reach * ppu)
    # the shift at which the model's ink near the letter best covers it
    k = max(1, round(max(canvas.size) / 256))
    a, b = (near & drawn)[::k, ::k].astype(float), letter[::k, ::k].astype(float)
    corr = np.fft.irfft2(np.fft.rfft2(a) * np.conj(np.fft.rfft2(b)), a.shape)
    lim = int(reach * ppu / k)
    dy, dx = np.meshgrid(np.arange(a.shape[0]), np.arange(a.shape[1]), indexing="ij")
    dy, dx = np.where(dy > a.shape[0] // 2, dy - a.shape[0], dy), np.where(dx > a.shape[1] // 2, dx - a.shape[1], dx)
    corr[(abs(dy) > lim) | (abs(dx) > lim)] = -1
    i = np.unravel_index(np.argmax(corr), corr.shape)
    sx, sy = float(dx[i] * k / ppu), float(dy[i] * k / ppu)   # right and down are positive
    union = (drawn & zone | letter).sum()
    return {"letter_iou": round(float((drawn & letter).sum() / union), 4) if union else None,
            "band": round(float(drawn[rim].mean()), 4) if rim.any() else None,
            "drift": round(math.hypot(sx, sy), 1), "drift_xy": [round(sx, 1), round(sy, 1)],
            "stretch": round(stretch, 4)}


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
