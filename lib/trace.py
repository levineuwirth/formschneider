"""Raster to outlines through potrace: one color by threshold, traced, and
the curves brought back into the initial's box."""

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path as File

from PIL import Image

from paths import Path, parse, transform
from raster import flatten


@dataclass(frozen=True)
class Cut:
    """potrace's knobs, named as its manual names them."""
    threshold: float = 0.5   # gray level below which a pixel is ink
    turdsize: int = 2        # speckles of at most this many pixels are dropped
    alphamax: float = 1.0    # corner threshold: lower keeps more corners
    opttolerance: float = 0.2  # how far curve joining may stray, in pixels


def trace(img: Image.Image, box: tuple[int, int], cut: Cut = Cut()) -> Path:
    gray = flatten(img)
    bw = gray.point(lambda v: 0 if v < cut.threshold * 255 else 255, "1")
    with tempfile.TemporaryDirectory() as tmp:
        pbm = File(tmp) / "in.pbm"
        bw.save(pbm)
        svg = subprocess.run(
            ["potrace", "-b", "svg", "--flat", "-t", str(cut.turdsize),
             "-a", str(cut.alphamax), "-O", str(cut.opttolerance), "-o", "-", str(pbm)],
            capture_output=True, text=True, check=True).stdout
    _, _, vw, vh = map(float, re.search(r'viewBox="([^"]+)"', svg).group(1).split())
    tx, ty, sx, sy = map(float, re.search(
        r"translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)", svg).groups())
    kx, ky = box[0] / vw, box[1] / vh
    path = [sub for d in re.findall(r' d="([^"]+)"', svg) for sub in parse(d)]
    return transform(path, lambda p: ((tx + sx * p[0]) * kx, (ty + sy * p[1]) * ky))
