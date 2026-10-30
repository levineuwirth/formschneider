"""A font's glyph as a Path in its own box: y down, origin at the top left
of its bounds, in font units, the frame the site's sets are drawn in."""

from fontTools.pens.basePen import (decomposeQuadraticSegment,
                                    decomposeSuperBezierSegment)
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

from paths import Path


def bounds(font: str, char: str) -> tuple[float, float, float, float]:
    f = TTFont(font)
    gs = f.getGlyphSet()
    bp = BoundsPen(gs)
    gs[f.getBestCmap()[ord(char)]].draw(bp)
    return bp.bounds


def glyph(font: str, char: str) -> tuple[Path, tuple[int, int]]:
    x0, y0, x1, y1 = bounds(font, char)
    path = outline(font, char, lambda p: (p[0] - x0, y1 - p[1]))
    return path, (round(x1 - x0), round(y1 - y0))


def outline(font: str, char: str, t) -> Path:
    """The glyph's contours, each point carried by t from font units."""
    f = TTFont(font)
    gs = f.getGlyphSet()
    rp = RecordingPen()
    gs[f.getBestCmap()[ord(char)]].draw(rp)
    path: Path = []
    sub, cur = [], (0.0, 0.0)
    for op, args in rp.value:
        if op == "moveTo":
            sub, cur = [("M", (t(args[0]),))], args[0]
        elif op == "lineTo":
            sub.append(("L", (t(args[0]),)))
            cur = args[0]
        elif op == "curveTo":
            for c1, c2, p in decomposeSuperBezierSegment(args):
                sub.append(("C", (t(c1), t(c2), t(p))))
                cur = p
        elif op == "qCurveTo":
            # TrueType's quadratics, raised to the cubics the site writes
            for q, p in decomposeQuadraticSegment(args):
                c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
                c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
                sub.append(("C", (t(c1), t(c2), t(p))))
                cur = p
        elif op in ("closePath", "endPath"):
            path.append(sub)
    return path
