"""An initial as levineuwirth.org's sets hold it (MARKS.md 2.6 there): the
outlines once as a hairline shade, once split into cuts that are drawn in
one by one from the top left, and once as the ink that fills them."""

import brotli
import re

from paths import Path, bounds, fmt

_DEFS = ('<defs><linearGradient id="initial-ink" x1="0" y1="0" x2="1" y2="1">'
         '<stop offset="0" style="stop-color:var(--initial-ink-lo, currentColor)"/>'
         '<stop offset="1" style="stop-color:var(--initial-ink-hi, currentColor)"/>'
         '</linearGradient></defs>')


def initial_svg(path: Path, box: tuple[int, int], credit: str) -> str:
    w, h = box
    d = fmt(path)
    cuts = []
    for sub in path:
        x0, y0, x1, y1 = bounds(sub)
        t = 0.45 + 0.3 * ((x0 + x1) / 2 / w + (y0 + y1) / 2 / h) / 2
        cuts.append(f'<path class="initial-cut" pathLength="1" style="--t:{t:.2f}s" '
                    f'd="{fmt([sub])}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'focusable="false"><!-- {credit} -->{_DEFS}'
            f'<path class="initial-shade" d="{d}" fill="none" stroke="url(#initial-ink)" '
            'stroke-width="0.6" vector-effect="non-scaling-stroke" opacity="0.7" '
            'transform="translate(22 22)"/>'
            '<g fill="none" stroke="url(#initial-ink)" stroke-width="0.45" '
            f'vector-effect="non-scaling-stroke">{"".join(cuts)}</g>'
            f'<path class="initial-ink" style="--t:1.05s" d="{d}" fill="url(#initial-ink)"/>'
            '</svg>')


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
