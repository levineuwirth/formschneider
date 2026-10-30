"""What every provider's adapter takes and gives, so the runner and the
record need know nothing of any one provider."""

from dataclasses import dataclass, field

import numpy as np
from PIL import Image


@dataclass
class Request:
    prompt: str
    size: tuple[int, int]
    image: Image.Image | None = None        # the canvas, for the ornament-only route
    editable: np.ndarray | None = None      # where the model may draw on it
    refs: list[tuple[str, Image.Image]] = field(default_factory=list)


@dataclass
class Result:
    png: bytes
    request_id: str | None = None
    seconds: float | None = None
    usage: dict | None = None
    meta: dict = field(default_factory=dict)
