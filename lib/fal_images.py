"""Image models through fal.ai's queue: many providers' models on one key.

Each endpoint takes its images and its size its own way; ENDPOINTS holds
what its page and schema said on 2026-11-03. On fal a mask's white is where
the model may draw: Ideogram's own API has it the other way, and fal's
example for its edit endpoint changes the white (81% of it) and leaves the
black (0.2% changed), though no page says so.

The queue is spoken over plain HTTP. fal's client library tries a backup
host when a connection fails, and no setting turns that off; a retry is
another request, perhaps billed, and the runner counts and records every
request it makes. So the library is used only for uploads, where a retry
costs nothing. Every submission refuses the queue's own retries
(X-Fal-No-Retry), and refuses fallbacks (x-app-fal-disable-fallback): a
fallback is another endpoint fal thinks equivalent, and nothing in the
answer would say that one had been used.

fal's endpoints have no dated snapshots, so the date in the record is all
that says which version of a model answered.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from fractions import Fraction
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image

from canvas import png
from model import NotSent, Request, Result

QUEUE = "https://queue.fal.run"
KEPT = 7 * 24 * 3600  # seconds fal holds its files; left unset, they are public and kept forever


@dataclass(frozen=True)
class Endpoint:
    sizing: str                 # "aspect": aspect_ratio, with the spec's resolution; "pixels": image_size
    max_images: int             # every image a request may carry, canvas and references
    seed: bool = False          # takes a seed
    inpaint: str | None = None  # where a canvas goes, with a mask, if not to this endpoint


ENDPOINTS = {
    "google/nano-banana-2.1/edit": Endpoint("aspect", 14, seed=True),
    "blackforestlabs/flux-3/edit-image": Endpoint("aspect", 10),
    "bytedance/seedream/v5/pro/edit": Endpoint("pixels", 10),
    "alibaba/qwen-image-3/edit": Endpoint("pixels", 3, seed=True),
    "fal-ai/ideogram/v3": Endpoint("pixels", 10, seed=True, inpaint="fal-ai/ideogram/v3/edit"),
}


def check(m: dict, refs: int) -> None:
    """A spec's model against its endpoint, before anything is sent."""
    e = ENDPOINTS.get(m["model"])
    if e is None:
        raise SystemExit(f"{m['model']}: not an endpoint this adapter knows")
    if not e.inpaint and m.get("max_images", refs + 1) > e.max_images:
        raise SystemExit(f"{m['model']}: takes {e.max_images} images at most; set max_images")
    if e.inpaint and refs > e.max_images:
        raise SystemExit(f"{m['model']}: takes {e.max_images} style references at most")
    if m.get("seeded") and not e.seed:
        raise SystemExit(f"{m['model']}: takes no seed")
    if e.sizing == "aspect" and "resolution" not in m.get("params", {}):
        raise SystemExit(f"{m['model']}: sets its size by aspect ratio and needs a resolution")


class FalError(Exception):
    """fal answered with an error. Its type goes in the record; its message,
    which can name an account, only to the terminal."""

    def __init__(self, response: httpx.Response, request_id: str | None = None):
        try:
            answer = response.json()
        except ValueError:
            answer = {}
        detail = answer.get("detail") if isinstance(answer, dict) else None
        kind = answer.get("error_type") or answer.get("type") if isinstance(answer, dict) else None
        if not kind and isinstance(detail, list) and detail and isinstance(detail[0], dict):
            kind = detail[0].get("type")
        self.status_code = response.status_code
        self.request_id = request_id or response.headers.get("x-fal-request-id")
        self.body = {"type": kind} if kind else None
        super().__init__(f"fal answered {response.status_code}: {detail}")


class FalLost(Exception):
    """fal took the request and what became of it is unknown here. It has no
    status, so the runner records the outcome as unknown, with the request
    id to look it up by: fal keeps results by that id for 90 days."""

    def __init__(self, why: str, request_id: str):
        self.request_id = request_id
        super().__init__(f"{why} (fal request {request_id})")


def mask_png(editable: np.ndarray) -> bytes:
    return png(Image.fromarray(np.where(editable, 255, 0).astype(np.uint8), "L"))


def _upload(data: bytes) -> str:
    import fal_client
    from fal_client.client import StorageSettings
    return fal_client.upload(data, "image/png", lifecycle=StorageSettings(expires_in="7d"))


class FalImages:
    def __init__(self, model: str, client=None, upload=_upload, key: str | None = None,
                 sleep=time.sleep, interval: float = 2.0, deadline: float = 900.0, **params):
        if model not in ENDPOINTS:
            raise SystemExit(f"{model}: not an endpoint this adapter knows")
        self.key = key or os.environ.get("FAL_KEY")
        if not self.key:
            raise SystemExit("FAL_KEY is not set: put it in .env")
        self.model, self.endpoint, self.params = model, ENDPOINTS[model], params
        self.client = client or httpx.Client(timeout=60.0)
        self.upload, self.sleep, self.interval, self.deadline = upload, sleep, interval, deadline
        self.urls: dict[str, str] = {}

    def _url(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.urls:
            try:
                self.urls[digest] = self.upload(data)
            except Exception as e:
                raise NotSent(f"an upload failed: {type(e).__name__}") from e
        return self.urls[digest]

    def _job(self, req: Request) -> tuple[str, dict]:
        """Which endpoint, and what it is sent."""
        e, path = self.endpoint, self.model
        if req.seed is not None and not e.seed:
            raise NotSent(f"{self.model} takes no seed")
        refs = [self._url(png(img)) for _, img in req.refs]
        body = dict(self.params, prompt=req.prompt)
        sized = True
        if req.image is None:
            body["image_urls"] = refs
        elif e.inpaint:
            path, sized = e.inpaint, False  # it answers at the canvas's size
            body |= {"image_url": self._url(png(req.image)),
                     "mask_url": self._url(mask_png(req.editable)), "image_urls": refs}
        else:
            body["image_urls"] = [self._url(png(req.image)), *refs]
        if len(body["image_urls"]) > e.max_images:
            raise NotSent(f"{self.model} takes {e.max_images} images at most")
        if sized and e.sizing == "aspect":
            ratio = Fraction(*req.size)
            body["aspect_ratio"] = f"{ratio.numerator}:{ratio.denominator}"
        elif sized:
            body["image_size"] = {"width": req.size[0], "height": req.size[1]}
        if req.seed is not None:
            body["seed"] = req.seed
        return path, body

    def _get(self, url: str, request_id: str, **kw) -> httpx.Response:
        """A read, which costs nothing, so it may be tried again."""
        for attempt in range(5):
            try:
                return self.client.get(url, **kw)
            except httpx.TransportError:
                self.sleep(self.interval)
        raise FalLost("fal could not be reached to read the answer", request_id)

    def __call__(self, req: Request) -> Result:
        path, body = self._job(req)
        auth = {"Authorization": f"Key {self.key}"}
        t0 = time.time()
        sent = self.client.post(f"{QUEUE}/{path}", json=body, headers=auth | {
            "X-Fal-No-Retry": "1", "x-app-fal-disable-fallback": "true",
            "X-Fal-Object-Lifecycle-Preference": json.dumps({"expiration_duration_seconds": KEPT})})
        if not sent.is_success:
            raise FalError(sent)
        job = sent.json()
        rid = job["request_id"]
        # the queue's own URLs: built from the endpoint's path they answer 405;
        # and the key goes only to the queue
        for url in (job["status_url"], job["response_url"]):
            if urlparse(url).hostname != urlparse(QUEUE).hostname:
                raise FalLost("fal's answer pointed somewhere else", rid)
        status = {}
        while status.get("status") != "COMPLETED":
            if time.time() - t0 > self.deadline:
                raise FalLost(f"no result after {self.deadline:.0f} s", rid)
            self.sleep(self.interval)
            polled = self._get(job["status_url"], rid, headers=auth)
            if polled.is_server_error:
                continue
            if polled.is_client_error:
                raise FalLost(f"the queue answered {polled.status_code} about it", rid)
            status = polled.json()
        done = self._get(job["response_url"], rid, headers=auth)
        if not done.is_success:
            raise FalError(done, rid)
        try:
            answer = done.json()
            image = answer["images"][0]
            picture = self._get(image["url"], rid, follow_redirects=True)  # no key: it is the CDN's
            picture.raise_for_status()
        except (KeyError, IndexError, TypeError, ValueError, httpx.HTTPStatusError) as e:
            raise FalLost(f"its picture could not be read: {type(e).__name__}", rid) from e
        units = next((r.headers["x-fal-billable-units"] for r in (done, sent)
                      if "x-fal-billable-units" in r.headers), None)
        usage = {"billable_units": units,
                 "inference_time": (status.get("metrics") or {}).get("inference_time")}
        meta = {"endpoint": path, "seed": answer.get("seed"),
                "has_nsfw_concepts": answer.get("has_nsfw_concepts"),
                **{k: image.get(k) for k in ("width", "height", "content_type", "file_size")}}
        return Result(png=picture.content, request_id=rid, seconds=round(time.time() - t0, 1),
                      usage={k: v for k, v in usage.items() if v is not None},
                      meta={k: v for k, v in meta.items() if v is not None})
