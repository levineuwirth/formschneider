"""fal's queue with no network and no key: a stand-in queue answers, so what
is sent, what comes back and what goes into the record can be checked."""

import io
import json
import sys
from pathlib import Path as File

import httpx
import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(File(__file__).resolve().parent.parent / "lib"))
import run
from canvas import png
from fal_images import ENDPOINTS, FalError, FalImages, FalLost, check
from model import NotSent, Request, Result, error_fields
from test_generate import SPEC, fake_adapter, quiet, saved

QUEUED = "https://queue.fal.run/owner/app/requests/r-1"
PIC = "https://v3.fal.media/files/out.png"
WHITE = png(Image.new("L", (8, 8), 255))


class Queue:
    """Answers as fal's queue does; `answers` overrides any URL's answer."""

    def __init__(self, polls: int = 1, **answers):
        self.seen: list[httpx.Request] = []
        self.polls, self.answers = polls, answers

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        url = str(request.url)
        if request.method == "POST":
            if "post" in self.answers:
                return self.answers["post"](request)
            return httpx.Response(200, json={"request_id": "r-1", "status_url": f"{QUEUED}/status",
                                             "response_url": QUEUED, "queue_position": 0})
        if url.endswith("/status"):
            if "status" in self.answers:
                return self.answers["status"](request)
            self.polls -= 1
            if self.polls > 0:
                return httpx.Response(202, json={"status": "IN_PROGRESS", "request_id": "r-1"})
            return httpx.Response(200, json={"status": "COMPLETED", "metrics": {"inference_time": 3.5}})
        if url == QUEUED:
            if "result" in self.answers:
                return self.answers["result"](request)
            return httpx.Response(200, headers={"x-fal-billable-units": "1"}, json={
                "seed": 7, "description": "not for the record",
                "images": [{"url": PIC, "width": 8, "height": 8, "content_type": "image/png"}]})
        if url == PIC and "picture" in self.answers:
            return self.answers["picture"](request)
        return httpx.Response(200, content=WHITE)

    def posted(self) -> tuple[str, dict]:
        (post,) = [r for r in self.seen if r.method == "POST"]
        return post.url.path.lstrip("/"), json.loads(post.content)


def fal(model: str, queue: Queue, **params) -> FalImages:
    uploads = []

    def upload(data: bytes) -> str:
        uploads.append(data)
        return f"https://up.example/{uploads.index(data)}.png"
    ai = FalImages(model, client=httpx.Client(transport=httpx.MockTransport(queue)), upload=upload,
                   key="k3y", sleep=lambda s: None, **params)
    ai.uploads = uploads
    return ai


REF = ("D", Image.new("L", (6, 4), 200))


def canvas() -> tuple[Image.Image, np.ndarray]:
    editable = np.zeros((4, 6), bool)
    editable[:, 3:] = True
    return Image.new("L", (6, 4), 255), editable


def test_a_request_goes_through_the_queue_once_refusing_retries_and_fallbacks():
    q = Queue(polls=2)
    res = fal("google/nano-banana-2.1/edit", q, resolution="1K")(Request("p", (1536, 1024), refs=[REF], seed=5))
    path, body = q.posted()
    assert path == "google/nano-banana-2.1/edit"
    assert body == {"prompt": "p", "resolution": "1K", "aspect_ratio": "3:2", "seed": 5,
                    "image_urls": ["https://up.example/0.png"]}
    post = next(r for r in q.seen if r.method == "POST")
    assert post.headers["authorization"] == "Key k3y"
    assert post.headers["x-fal-no-retry"] == "1" and post.headers["x-app-fal-disable-fallback"] == "true"
    assert json.loads(post.headers["x-fal-object-lifecycle-preference"])["expiration_duration_seconds"] > 0
    assert [str(r.url) for r in q.seen[1:]] == [f"{QUEUED}/status"] * 2 + [QUEUED, PIC]
    assert "authorization" not in q.seen[-1].headers    # the key goes to the queue alone
    assert res.png == WHITE and res.request_id == "r-1"
    assert res.usage == {"billable_units": "1", "inference_time": 3.5}
    assert res.meta == {"endpoint": path, "seed": 7, "width": 8, "height": 8, "content_type": "image/png"}


def test_each_endpoint_takes_its_images_and_its_size_its_own_way():
    image, editable = canvas()
    q = Queue()
    ai = fal("bytedance/seedream/v5/pro/edit", q, watermark=False)
    ai(Request("p", (6, 4), image, editable, [REF]))
    path, body = q.posted()
    assert path == "bytedance/seedream/v5/pro/edit" and body["watermark"] is False
    sent = [ai.uploads[int(u[-5])] for u in body["image_urls"]]
    assert sent == [png(image), png(REF[1])]                # the canvas first
    assert body["image_size"] == {"width": 6, "height": 4} and "mask_url" not in body

    q = Queue()
    ai = fal("fal-ai/ideogram/v3", q)
    ai(Request("p", (1024, 1024), refs=[REF]))
    path, body = q.posted()
    assert path == "fal-ai/ideogram/v3" and body["image_size"] == {"width": 1024, "height": 1024}

    q = Queue()
    ai = fal("fal-ai/ideogram/v3", q)
    ai(Request("p", (6, 4), image, editable, [REF]))
    path, body = q.posted()
    assert path == "fal-ai/ideogram/v3/edit" and "image_size" not in body
    assert len(body["image_urls"]) == 1 and body["image_url"] != body["mask_url"] != body["image_urls"][0]
    mask = Image.open(io.BytesIO(ai.uploads[int(body["mask_url"][-5])]))
    assert mask.size == image.size and mask.mode == "L"
    assert (np.asarray(mask)[editable] == 255).all() and (np.asarray(mask)[~editable] == 0).all()


def test_an_image_is_uploaded_once():
    q = Queue(polls=-99)
    ai = fal("alibaba/qwen-image-3/edit", q)
    for _ in range(2):
        ai(Request("p", (6, 4), refs=[REF]))
    assert len(ai.uploads) == 1


def test_too_much_for_an_endpoint_is_not_sent():
    q = Queue()
    with pytest.raises(NotSent):
        fal("alibaba/qwen-image-3/edit", q)(Request("p", (6, 4), refs=[(str(k), Image.new("L", (6, 4), k))
                                                                        for k in range(4)]))
    with pytest.raises(NotSent):
        fal("blackforestlabs/flux-3/edit-image", q)(Request("p", (6, 4), refs=[REF], seed=1))
    assert not q.seen


def test_an_error_keeps_its_status_and_type_and_not_its_message():
    answer = lambda r: httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "acct-42 says no",
                                                             "type": "value_error.missing"}]})
    with pytest.raises(FalError) as e:
        fal("alibaba/qwen-image-3/edit", Queue(post=answer))(Request("p", (6, 4), refs=[REF]))
    assert error_fields(e.value) == {"class": "FalError", "status": 422, "type": "value_error.missing"}

    answer = lambda r: httpx.Response(500, json={"detail": "acct-42 broke", "error_type": "runner_server_error"})
    with pytest.raises(FalError) as e:
        fal("alibaba/qwen-image-3/edit", Queue(result=answer))(Request("p", (6, 4), refs=[REF]))
    assert error_fields(e.value) == {"class": "FalError", "status": 500, "request_id": "r-1",
                                     "type": "runner_server_error"}


def test_no_answer_to_a_submission_is_not_tried_again():
    def timeout(request):
        raise httpx.ReadTimeout("no answer")
    q = Queue(post=timeout)
    with pytest.raises(httpx.ReadTimeout) as e:
        fal("alibaba/qwen-image-3/edit", q)(Request("p", (6, 4), refs=[REF]))
    assert len(q.seen) == 1 and "status" not in error_fields(e.value)


def test_a_request_taken_and_lost_is_recorded_with_its_id():
    req = Request("p", (6, 4), refs=[REF])
    model = "alibaba/qwen-image-3/edit"
    with pytest.raises(FalLost) as e:                                   # no result by the deadline
        fal(model, Queue(), deadline=-1)(req)
    assert error_fields(e.value) == {"class": "FalLost", "request_id": "r-1"}

    answer = lambda r: httpx.Response(404, json={"status": "NOT_FOUND"})
    with pytest.raises(FalLost):                                        # the queue no longer knows it
        fal(model, Queue(status=answer))(req)
    with pytest.raises(FalLost):                                        # done, but no picture to fetch
        fal(model, Queue(picture=lambda r: httpx.Response(404)))(req)
    with pytest.raises(FalLost):                                        # an answer with no picture in it
        fal(model, Queue(result=lambda r: httpx.Response(200, json={"images": []})))(req)


def test_reading_is_tried_again_since_it_costs_nothing():
    down = iter([True, False])

    def flaky(request):
        if next(down):
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"status": "COMPLETED"})
    q = Queue(status=flaky)
    assert fal("alibaba/qwen-image-3/edit", q)(Request("p", (6, 4), refs=[REF])).request_id == "r-1"
    assert sum(r.method == "POST" for r in q.seen) == 1


def test_the_key_is_not_sent_where_the_queue_did_not_say():
    answer = lambda r: httpx.Response(200, json={"request_id": "r-1", "status_url": "https://elsewhere.example/s",
                                                 "response_url": QUEUED})
    q = Queue(post=answer)
    with pytest.raises(FalLost):
        fal("alibaba/qwen-image-3/edit", q)(Request("p", (6, 4), refs=[REF]))
    assert len(q.seen) == 1


def test_a_spec_is_checked_against_its_endpoint():
    fine = {"model": "alibaba/qwen-image-3/edit", "max_images": 3}
    check(fine, 6)
    for wrong in ({"model": "nobody/nothing"}, {"model": "alibaba/qwen-image-3/edit"},
                  {"model": "blackforestlabs/flux-3/edit-image", "params": {"resolution": "1k"}, "seeded": True},
                  {"model": "blackforestlabs/flux-3/edit-image"}):
        with pytest.raises(SystemExit):
            check(wrong, 6)


@pytest.mark.parametrize("name,count", [("matched-rinceau", 288), ("pilot-ornament-prompt", 12)])
def test_the_runs_prepared_fit_their_endpoints_and_their_ceilings(name, count):
    spec = run.load(name)
    for m in spec["model"]:
        if m["provider"] == "fal":
            check(m, len(spec["refs"]["letters"]))
    jobs = run.plan(spec)
    assert len(jobs) == count == len({j.id for j in jobs}) and count <= spec["max_requests"]
    assert {m["model"] for m in spec["model"] if m["provider"] == "fal"} <= set(ENDPOINTS)


@pytest.fixture
def small(tmp_path):
    (tmp_path / "runs" / "t").mkdir(parents=True)
    (tmp_path / "runs" / "t" / "spec.toml").write_text(SPEC.replace('letters = "D"', 'letters = "DGL"'))
    spec = run.load("t", tmp_path)
    spec["letters"], spec["attempts"] = "F", 1
    return spec, tmp_path


def test_a_model_of_few_images_takes_the_first_references_and_a_seed_follows_from_the_job(small):
    spec, root = small
    spec["model"][0] |= {"max_images": 2, "seeded": True}
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    recs = {r["route"]: r for r in saved(spec, root)}
    assert list(recs["whole"]["inputs"]["refs"]) == ["D", "G"]
    assert list(recs["ornament"]["inputs"]["refs"]) == ["D"]
    assert recs["whole"]["seed"] != recs["ornament"]["seed"]
    job = next(j for j in run.plan(spec) if j.route == "whole")
    again, _ = run.request(spec, job, [])
    assert again.seed == recs["whole"]["seed"]


def test_a_request_that_never_left_is_a_failure_and_not_an_unknown(small):
    spec, root = small

    def unsent(model, **params):
        def call(req):
            raise NotSent("an upload failed")
        return call
    with pytest.raises(NotSent):
        run.execute(spec, {"fake": unsent}, go=True, root=root, log=quiet)
    assert [e["event"] for e in run.events(spec, root)] == ["sent", "failed"]
    assert run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)  # no --abandon needed


def test_a_picture_is_named_for_what_it_is_and_finished_all_the_same(small):
    spec, root = small
    spec["routes"] = ["whole"]

    def jpeg(model, **params):
        draw = fake_adapter(model, **params)

        def call(req):
            buf = io.BytesIO()
            Image.open(io.BytesIO(draw(req).png)).save(buf, "JPEG")
            return Result(buf.getvalue(), request_id="req_j", seconds=0.0)
        return call
    run.execute(spec, {"fake": jpeg}, go=True, root=root, log=quiet)
    (rec,) = saved(spec, root)
    assert rec["output"]["file"].endswith(".jpg")
    assert run.finish(spec, root)[0]["path_bytes"] > 0

    f = root / "runs/t/records.jsonl"
    f.write_text("".join(line + "\n" for line in f.read_text().splitlines()[:2]))  # lost "saved"
    assert run.execute(spec, {"fake": jpeg}, go=True, root=root, log=quiet) == []
    assert saved(spec, root)[0]["output"]["file"].endswith(".jpg")
