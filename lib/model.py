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


_WORD = r"[a-z0-9_.]{1,64}"
_ID = r"[A-Za-z0-9_-]{1,128}"


def error_fields(e: BaseException) -> dict:
    """What of a failure may go into the record: its class, the HTTP status,
    the request id, and the provider's error type and code when they are
    plain lowercase words. Never the message, which can name an account."""
    import re
    out = {"class": type(e).__name__}
    if isinstance(getattr(e, "status_code", None), int):
        out["status"] = e.status_code
    rid = getattr(e, "request_id", None)
    if rid is None and getattr(e, "response", None) is not None:
        rid = e.response.headers.get("x-request-id")
    if isinstance(rid, str) and re.fullmatch(_ID, rid):
        out["request_id"] = rid
    body = getattr(e, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else None
    for k in ("type", "code"):
        v = err.get(k) if isinstance(err, dict) else None
        if isinstance(v, str) and re.fullmatch(_WORD, v):
            out[k] = v
    return out
