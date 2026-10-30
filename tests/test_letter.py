"""The kept capital: one size and baseline for every letter, wide blocks
for wide letters."""

import sys
from pathlib import Path as File

import pytest

sys.path.insert(0, str(File(__file__).resolve().parent.parent / "lib"))
from letter import SPECTRAL, capital

FONT = SPECTRAL.format(weight="SemiBold")
pytestmark = pytest.mark.skipif(not File(FONT).exists(), reason="Spectral not found")


def extent(path):
    ys = [y for sub in path for _, pts in sub for _, y in pts]
    xs = [x for sub in path for _, pts in sub for x, _ in pts]
    return min(xs), min(ys), max(xs), max(ys)


def test_every_letter_stands_on_one_baseline_at_one_height():
    for c in "IFW":
        path, (w, h) = capital(FONT, c)
        x0, y0, x1, y1 = extent(path)
        # pointed and round letters overshoot the baseline and cap height a little
        assert h == 1000 and y1 == pytest.approx(910, abs=8) and y0 == pytest.approx(90, abs=8)
        assert x0 > 0 and x1 < w and (x0 + x1) / 2 == pytest.approx(w / 2, abs=1)


def test_a_wide_letter_widens_its_block():
    assert capital(FONT, "I")[1] == (1000, 1000)
    w, _ = capital(FONT, "W")[1]
    assert w > 1100
