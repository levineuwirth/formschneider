"""A picture made ready for the cut: cropped to the initial, its light
leveled, cleaned of specks, and brought to the width the cut works at."""

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from raster import flatten


@dataclass(frozen=True)
class Prep:
    width: int | None = None  # long side to resample to; None keeps the picture's own
    median: int = 0           # median filter's size before resampling; 0 for none
    level: bool = False       # divide out uneven light (a photographed page)


def prepare(img: Image.Image, prep: Prep = Prep(), crop=None) -> Image.Image:
    gray = flatten(img)
    if crop:
        gray = gray.crop(tuple(crop))
    if prep.level:
        # the page's light, from a blur wide enough to lose the ink
        light = np.asarray(gray.filter(ImageFilter.GaussianBlur(max(gray.size) / 30)), float)
        page = np.asarray(gray, float)
        gray = Image.fromarray(np.clip(page / np.maximum(light, 1) * 255, 0, 255).astype(np.uint8))
    if prep.median:
        gray = gray.filter(ImageFilter.MedianFilter(prep.median))
    if prep.width:
        k = prep.width / max(gray.size)
        gray = gray.resize((round(gray.width * k), round(gray.height * k)),
                           Image.Resampling.LANCZOS)
    return gray


def otsu(gray: Image.Image) -> float:
    """The gray level that best splits ink from ground, as a fraction."""
    hist = np.bincount(np.asarray(gray).ravel(), minlength=256).astype(float)
    p = hist / hist.sum()
    w = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu[-1] * w - mu) ** 2 / (w * (1 - w))
    return float(np.nanargmax(between)) / 255


def box_for(size: tuple[int, int], long: int = 1000) -> tuple[int, int]:
    """An initial's frame: the picture's proportions, its long side in the
    thousand units the font's initials use."""
    k = long / max(size)
    return round(size[0] * k), round(size[1] * k)
