"""Pictures as the tracer and the measures see them: grayscale, ink dark on
a white ground. rsvg-convert draws SVG; PIL reads everything else."""

import io
import subprocess

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from paths import Path, fmt


def bare_svg(path: Path, box: tuple[int, int]) -> str:
    """The outlines alone, filled black: what a path looks like as ink."""
    w, h = box
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'<path d="{fmt(path)}"/></svg>')


def rasterize(svg: str, width: int) -> Image.Image:
    png = subprocess.run(["rsvg-convert", "-w", str(width), "-b", "white"],
                         input=svg.encode(), capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(png)).convert("L")


def flatten(img: Image.Image) -> Image.Image:
    """Any picture onto white, in gray; transparency reads as ground."""
    if img.mode in ("RGBA", "LA", "P"):
        ground = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(ground, img.convert("RGBA"))
    return img.convert("L")


def ink(img: Image.Image, threshold: float = 0.5) -> np.ndarray:
    return np.asarray(img) < threshold * 255


def iou(a: Image.Image, b: Image.Image) -> float:
    """Agreement of two pictures' ink, as intersection over union."""
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.LANCZOS)
    x, y = ink(a), ink(b)
    union = (x | y).sum()
    return float((x & y).sum() / union) if union else 1.0


def edge(img: Image.Image) -> np.ndarray:
    """Ink pixels with ground beside them: the outline, a pixel wide."""
    a = ink(img)
    p = np.pad(a, 1)
    return a & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])


def deviation(a: Image.Image, b: Image.Image, q: float = 95) -> tuple[float, float]:
    """How far b's outline strays from a's, and how far a's lies from b's
    (what b lost), each as the q-th percentile of distance, in a's pixels.
    Unlike IoU, a shift of a pixel counts as a pixel however thin the stroke."""
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.LANCZOS)
    ea, eb = edge(a), edge(b)
    if not ea.any() or not eb.any():
        return float("inf"), float("inf")
    return (float(np.percentile(distance_transform_edt(~ea)[eb], q)),
            float(np.percentile(distance_transform_edt(~eb)[ea], q)))
