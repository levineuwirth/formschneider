"""The site's capital set in an initial's block: the letter the
ornament-only route keeps, which the model is never asked to draw."""

from fontTools.ttLib import TTFont

from glyph import bounds, outline
from paths import Path

SPECTRAL = "/usr/share/texmf-dist/fonts/truetype/production/spectral/Spectral-{weight}.ttf"


def capital(font: str, char: str, height: int = 1000, cap: float = 0.82,
            fit: float = 0.9) -> tuple[Path, tuple[int, int]]:
    """The capital centered in its block, its cap height `cap` of the
    block's height (EB Garamond Initials' letters fill about 0.82), at one
    size and on one baseline for every letter of the font. The block is
    square unless the letter is wider than `fit` of it (W, M), and then it
    widens: the site sizes an initial by its height, so a wide block costs
    nothing, and the letter keeps its size."""
    s = cap * height / TTFont(font)["OS/2"].sCapHeight
    x0, _, x1, _ = bounds(font, char)
    width = max(height, round(s * (x1 - x0) / fit))
    dx = width / 2 - s * (x0 + x1) / 2
    base = (height + cap * height) / 2
    return outline(font, char, lambda p: (dx + s * p[0], base - s * p[1])), (width, height)
