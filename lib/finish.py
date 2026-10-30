"""The fixed finishing every picture gets, whichever model drew it, and what
it is measured by. The setting is the one the scans bench calls blind,
fixed there on woodcut scans before any generated picture was seen, so
no model's results choose their own finishing."""

from PIL import Image

from initial import measure
from paths import Path
from prepare import Prep, box_for, otsu, prepare
from raster import bare_svg, deviation, edge, iou, rasterize
from simplify import simplify
from trace import Cut, trace

FINISH = dict(width=2048, median=3, speck=20, tolerance=2)
BUDGET = 17996  # EB Garamond Initials' F, the home page's: path data in bytes
EVAL = 1000


def threshold(gray: Image.Image) -> Image.Image:
    t = otsu(gray) * 255
    return gray.point(lambda v: 0 if v < t else 255)


def cut(gray: Image.Image) -> tuple[Path, tuple[int, int]]:
    pic = prepare(gray, Prep(width=FINISH["width"], median=FINISH["median"]))
    box = box_for(pic.size)
    px = max(pic.size) / 1000
    traced = trace(pic, box, Cut(threshold=otsu(pic), turdsize=round(FINISH["speck"] * px * px)))
    return simplify(traced, FINISH["tolerance"]), box


def measures(gray: Image.Image, path: Path, box: tuple[int, int], svg: str) -> dict:
    """Cost (the file, the outlines, against the budget), the picture's edge
    and bytes per unit of it, and fidelity to the picture (deviation both
    ways in units, and IoU), all at EVAL px as the scans bench measures."""
    ref = threshold(prepare(gray, Prep(width=EVAL)))
    drawn = rasterize(bare_svg(path, box), ref.width)
    m = measure(path, svg)
    e = int(edge(ref).sum())
    strays, lost = deviation(ref, drawn)
    return {**m, "edge": e, "per_edge": round(m["path_bytes"] / e, 3) if e else None,
            "budget": round(m["path_bytes"] / BUDGET, 3), "strays": strays, "lost": lost,
            "iou": round(iou(ref, drawn), 4)}
