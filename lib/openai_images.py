"""GPT Image through OpenAI's images API.

With no input image and no references a job is a plain generation; with
either it goes to the edits endpoint, which takes several images. The
canvas comes first, when there is one, and the mask applies to it; the
references follow. OpenAI's mask is a PNG whose transparent pixels are
where the model may draw, and the docs say the model may not follow its
exact shape, which is why canvas.put_back restores the letter afterwards.
"""

import base64
import time

import numpy as np
from PIL import Image

from canvas import png
from model import Request, Result


def mask_png(editable: np.ndarray) -> bytes:
    rgba = np.zeros((*editable.shape, 4), np.uint8)
    rgba[..., 3] = np.where(editable, 0, 255)
    return png(Image.fromarray(rgba, "RGBA"))


class OpenAIImages:
    def __init__(self, model: str, client=None, **params):
        if client is None:
            import openai  # only when a request is really to be made
            client = openai.OpenAI()
        self.client, self.model, self.params = client, model, params

    def __call__(self, req: Request) -> Result:
        args = dict(model=self.model, prompt=req.prompt, n=1,
                    size=f"{req.size[0]}x{req.size[1]}", **self.params)
        images = ([("canvas.png", png(req.image), "image/png")] if req.image is not None else [])
        images += [(f"ref-{name}.png", png(img), "image/png") for name, img in req.refs]
        t0 = time.time()
        if not images:
            raw = self.client.images.with_raw_response.generate(**args)
        else:
            if req.editable is not None:
                args["mask"] = ("mask.png", mask_png(req.editable), "image/png")
            raw = self.client.images.with_raw_response.edit(image=images, **args)
        r = raw.parse()
        return Result(
            png=base64.b64decode(r.data[0].b64_json),
            request_id=raw.headers.get("x-request-id"),
            seconds=round(time.time() - t0, 1),
            usage=r.usage.model_dump() if getattr(r, "usage", None) else None,
            meta={k: v for k, v in {"revised_prompt": getattr(r.data[0], "revised_prompt", None),
                                    "created": getattr(r, "created", None)}.items() if v},
        )
