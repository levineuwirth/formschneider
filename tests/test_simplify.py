"""The refit: fewer curves, within its tolerance, corners kept."""

import math
import sys
from pathlib import Path as File

import numpy as np
import pytest

sys.path.insert(0, str(File(__file__).resolve().parent.parent / "lib"))
from glyph import glyph
from paths import fmt
from raster import bare_svg, deviation, rasterize
from simplify import simplify
from test_cut import EBGI, needs_font


def sample(sub, n=50):
    pts, p = [], np.array(sub[0][1][0])
    for op, seg in sub[1:]:
        c = np.array([p, *seg])
        for t in np.linspace(0, 1, n):
            pts.append((1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1]
                       + 3 * (1 - t) * t ** 2 * c[2] + t ** 3 * c[3])
        p = c[-1]
    return np.array(pts)


def test_a_polygon_circle_becomes_a_few_curves_on_the_circle():
    ring = [(500 + 100 * math.cos(a), 500 + 100 * math.sin(a))
            for a in np.linspace(0, 2 * math.pi, 200, endpoint=False)]
    path = [[("M", (ring[0],))] + [("L", (q,)) for q in ring[1:]]]
    (sub,) = simplify(path, 0.5)
    assert len(sub) - 1 <= 8
    r = np.linalg.norm(sample(sub) - 500, axis=1)
    assert np.all(np.abs(r - 100) < 1)


def test_corners_are_kept():
    square = [(100, 100), (400, 100), (400, 400), (100, 400)]
    path = [[("M", (square[0],))] + [("L", (q,)) for q in square[1:]]]
    (sub,) = simplify(path, 1)
    ends = {tuple(np.round(seg[-1]).astype(int)) for _, seg in sub}
    assert set(square) <= ends


@needs_font
def test_a_drawn_initial_refits_within_its_tolerance():
    path, box = glyph(EBGI, "O")
    refit = simplify(path, 2)
    a, b = rasterize(bare_svg(path, box), 1000), rasterize(bare_svg(refit, box), 1000)
    assert max(deviation(a, b)) <= 3
    assert len(fmt(refit)) < 1.5 * len(fmt(path))
