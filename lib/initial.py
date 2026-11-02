"""An initial as levineuwirth.org's sets hold it (MARKS.md 2.6 there): the
outlines once as a hairline shade, once split into cuts that are drawn in
one by one from the top left, and once as the ink that fills them.

Each cut is drawn in at a moment set by where it starts along the
diagonal, over the span the site's EB Garamond set uses (within 0.07 s of
its every cut; it keeps no rule of its own to copy). An initial whose
letter is known apart from its ornament (the ornament-only route's kept
capital) carries that letter's own outline too, and its cuts are what grew
from it, so the page's stages can show the letter alone: a Draft is the
letter in pencil."""

import brotli
import re

from paths import Path, fmt

_DEFS = ('<defs><linearGradient id="initial-ink" x1="0" y1="0" x2="1" y2="1">'
         '<stop offset="0" style="stop-color:var(--initial-ink-lo, currentColor)"/>'
         '<stop offset="1" style="stop-color:var(--initial-ink-hi, currentColor)"/>'
         '</linearGradient></defs>')


def initial_svg(path: Path, box: tuple[int, int], credit: str,
                outline: Path | None = None) -> str:
    """The initial's SVG. With `outline`, the letter's own outline in the same
    frame, the cuts are marked as grown from it (.initial-growth), each
    keeping its hairline itself, as the site's CSS sets vector-effect only
    on cuts that are not growth; the outline (.initial-outline) shows when
    the page's stage draws the letter alone."""
    w, h = box
    d = fmt(path)
    grown = outline is not None
    cls = "initial-cut initial-growth" if grown else "initial-cut"
    hair = ' vector-effect="non-scaling-stroke"' if grown else ""
    cuts = []
    for sub in path:
        sx, sy = sub[0][1][0]
        t = 0.12 + 0.79 * (sx / w + sy / h) / 2
        cuts.append(f'<path class="{cls}" pathLength="1" style="--t:{t:.2f}s"{hair} '
                    f'd="{fmt([sub])}"/>')
    letter = ("" if not grown else
              '<path class="initial-cut initial-outline" pathLength="1" style="--t:0.12s;--d:0.6s" '
              f'd="{fmt(outline)}" fill="none" stroke="url(#initial-ink)" stroke-width="0.7" '
              'vector-effect="non-scaling-stroke"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'focusable="false"><!-- {credit} -->{_DEFS}'
            f'<path class="initial-shade" d="{d}" fill="none" stroke="url(#initial-ink)" '
            'stroke-width="0.6" vector-effect="non-scaling-stroke" opacity="0.7" '
            'transform="translate(22 22)"/>'
            '<g fill="none" stroke="url(#initial-ink)" stroke-width="0.45" '
            f'vector-effect="non-scaling-stroke">{"".join(cuts)}</g>{letter}'
            f'<path class="initial-ink" style="--t:1.05s" d="{d}" fill="url(#initial-ink)"/>'
            '</svg>\n')


def measure(path: Path, svg: str) -> dict:
    """What an initial costs the page: the outlines' own data, which the file
    carries three times, and the file as sent (the site serves brotli)."""
    d = fmt(path)
    return {
        "subpaths": len(path),
        "commands": len(re.findall(r"[MLCZ]", d)),
        "path_bytes": len(d),
        "svg_bytes": len(svg.encode()),
        "br_bytes": len(brotli.compress(svg.encode())),
    }
