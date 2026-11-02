"""The fixed finishing every picture gets, whichever model drew it, and what
it is measured by. The setting is the one the scans bench calls blind,
fixed there on woodcut scans before any generated picture was seen, so
no model's results choose their own finishing; the trial's comparison is
made at it.

The site's cut is fitted to the budget after (decided 2026-11-02, once the
pilot had been seen): the tightest tolerance on the ladder whose path data
fits, capped. Every route and model gets the same rule, and the tolerance
it took is reported beside the size, so the smoothing an initial needed
to fit stays visible. The author reviews each fitted cut against the
fixed one, and may take a tighter tolerance, over budget, when smoothing
damages the drawing."""

from PIL import Image

from initial import measure
from paths import Path, fmt
from prepare import Prep, box_for, otsu, prepare
from raster import bare_svg, deviation, edge, iou, rasterize
from simplify import simplify
from trace import Cut, trace

FINISH = dict(width=2048, median=3, speck=20, tolerance=2)
BUDGET = 17996  # EB Garamond Initials' F, the home page's: path data in bytes
EVAL = 1000
LADDER = (2, 3, 4, 5, 6, 8)  # the fit's tolerances, tightest (the fixed finishing's) first; 8 the cap
# An initial's height on the page in CSS px: three lines of 23 px Spectral at
# line height 1.65, 2 x 1.65 x 23 + 0.66 x 23 (the site's typography.css).
DISPLAY_PX = 91.08


def threshold(gray: Image.Image) -> Image.Image:
    t = otsu(gray) * 255
    return gray.point(lambda v: 0 if v < t else 255)


def traced(gray: Image.Image) -> tuple[Path, tuple[int, int]]:
    """The finishing up to the refit: prepared, thresholded, traced."""
    pic = prepare(gray, Prep(width=FINISH["width"], median=FINISH["median"]))
    box = box_for(pic.size)
    px = max(pic.size) / 1000
    return trace(pic, box, Cut(threshold=otsu(pic), turdsize=round(FINISH["speck"] * px * px))), box


def cut(gray: Image.Image) -> tuple[Path, tuple[int, int]]:
    path, box = traced(gray)
    return simplify(path, FINISH["tolerance"]), box


def fitted(raw: Path, budget: int = BUDGET, ladder: tuple = LADDER) -> tuple[Path, float]:
    """The traced outlines refit at the tightest tolerance on the ladder whose
    path data fits the budget, or at the cap when none does."""
    for t in ladder:
        path = simplify(raw, t)
        if len(fmt(path)) <= budget:
            break
    return path, t


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
