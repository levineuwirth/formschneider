"""The cut against outlines whose truth is known: EB Garamond Initials, and
the set levineuwirth.org already holds of it."""

import os
import re
import sys
from pathlib import Path as File

import pytest

sys.path.insert(0, str(File(__file__).resolve().parent.parent / "lib"))
from fonts import EBGI
from glyph import glyph
from paths import fmt, parse
from raster import bare_svg, iou, rasterize
from trace import trace

SET = File(os.environ.get(
    "FORMSCHNEIDER_SITE_SET",
    File.home() / "Repos/personal/levineuwirth.org/static/initials/eb-garamond"))

needs_font = pytest.mark.skipif(not File(EBGI).exists(), reason="no EB Garamond Initials: run bin/fonts")


def test_potrace_relative_data_reads_absolute():
    # c's points are all relative to the segment's start; m after z to the subpath's
    p = parse("M10 20c1 1 2 2 3 3l5 0zm1 1l1 0z")
    assert fmt(p) == "M10,20C11,21 12,22 13,23L18,23ZM11,21L12,21Z"


@needs_font
@pytest.mark.skipif(not SET.is_dir(), reason="levineuwirth.org's set not found")
@pytest.mark.parametrize("c", "ADFGLNOQTX")
def test_font_outlines_are_the_sites(c):
    site = (SET / f"{c}.svg").read_text()
    d = re.search(r'class="initial-ink"[^>]*d="([^"]+)"', site).group(1)
    path, (w, h) = glyph(EBGI, c)
    assert fmt(path) == d
    assert f'viewBox="0 0 {w} {h}"' in site
    assert fmt(parse(d)) == d


@needs_font
def test_trace_recovers_a_drawn_initial():
    path, box = glyph(EBGI, "O")
    ref = rasterize(bare_svg(path, box), 500)
    traced = trace(rasterize(bare_svg(path, box), 1024), box)
    assert iou(ref, rasterize(bare_svg(traced, box), 500)) > 0.97
