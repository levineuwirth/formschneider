"""The generation side, with no model and no network: a fake adapter and a
fake OpenAI client stand in, so what is sent, what is recorded and what is
finished can be checked exactly."""

import base64
import json
import re
import sys
from pathlib import Path as File
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(File(__file__).resolve().parent.parent / "lib"))
import env
import run
from canvas import letter_canvas, png, put_back
from fonts import EBGI, SPECTRAL
from glyph import glyph
from letter import capital
from model import Request, Result
from model import error_fields as model_error_fields
from openai_images import OpenAIImages
from raster import bare_svg, rasterize

pytestmark = pytest.mark.skipif(not (File(EBGI).exists() and File(SPECTRAL.format(weight="SemiBold")).exists()),
                                reason="no fonts: run bin/fonts")

SPEC = """\
letters = "FW"
attempts = 2
routes = ["whole", "ornament"]
max_requests = 10
[letter]
weight = "SemiBold"
cap = 0.82
grow = 10
[refs]
letters = "D"
[[model]]
provider = "fake"
model = "ebgi-2026-10-30"
name = "ebgi"
sizes = [[256, 256], [384, 256]]
params = { quality = "low" }
est_usd = 0.01
terms = "Test terms."
[prompt]
whole = "the letter {letter}"
ornament = "around the letter {letter}"
"""


def test_env_reads_values_and_never_comments():
    got = env.parse('A=1\n# B=2\nC=    # a note\nD="x y"\nexport E=3  # note\nF=a#b\n')
    assert got == {"A": "1", "D": "x y", "E": "3", "F": "a#b"}


def test_the_letter_and_its_halo_are_kept_and_put_back():
    path, box = capital(SPECTRAL.format(weight="SemiBold"), "F")
    canvas, editable, lay = letter_canvas(path, box, (256, 256), grow=10)
    letter = np.asarray(canvas) < 128
    assert not editable[letter].any() and editable.mean() > 0.5
    halo = ~editable & ~letter
    assert halo.any()
    back = np.asarray(put_back(Image.new("L", (512, 512), 0), canvas, editable, lay))
    up = np.asarray(Image.fromarray(editable).resize((512, 512), Image.Resampling.NEAREST))
    assert (back[up] == 0).all()                          # the model's picture where it may draw
    kept = np.asarray(canvas.resize((512, 512), Image.Resampling.LANCZOS))[~up]
    assert (back[~up] == kept).all()                      # the canvas everywhere else


class FakeImages:
    def __init__(self):
        self.calls = []

    @property
    def with_raw_response(self):
        return self

    def _reply(self):
        data = base64.b64encode(png(Image.new("L", (8, 8), 255))).decode()
        return SimpleNamespace(headers={"x-request-id": "req_fake"},
                               parse=lambda: SimpleNamespace(
                                   data=[SimpleNamespace(b64_json=data, revised_prompt=None)],
                                   usage=None, created=1))

    def generate(self, **kw):
        self.calls.append(("generate", kw))
        return self._reply()

    def edit(self, **kw):
        self.calls.append(("edit", kw))
        return self._reply()


def test_openai_generates_without_inputs_and_edits_with_them():
    client = SimpleNamespace(images=FakeImages())
    ai = OpenAIImages("gpt-image-test", client=client, quality="high")
    res = ai(Request("p", (1536, 1024)))
    kind, kw = client.images.calls[-1]
    assert kind == "generate" and kw["size"] == "1536x1024" and kw["quality"] == "high"
    assert res.request_id == "req_fake"

    editable = np.zeros((4, 6), bool)
    editable[:, 3:] = True
    ref = ("D", Image.new("L", (6, 4), 255))
    ai(Request("p", (6, 4), Image.new("L", (6, 4), 255), editable, [ref]))
    kind, kw = client.images.calls[-1]
    assert kind == "edit"
    assert [name for name, _, _ in kw["image"]] == ["canvas.png", "ref-D.png"]
    alpha = np.asarray(Image.open(__import__("io").BytesIO(kw["mask"][1])))[..., 3]
    assert (alpha[editable] == 0).all() and (alpha[~editable] == 255).all()


def fake_adapter(model, **params):
    """Draws EB Garamond Initials' F, whatever it is asked."""
    path, box = glyph(EBGI, "F")

    def draw(req: Request) -> Result:
        pic = rasterize(bare_svg(path, box), req.size[1]).resize(req.size)
        return Result(png(pic), request_id="req_fake", seconds=0.0, usage={"tokens": 1})
    return draw


def test_the_openai_client_never_retries_on_its_own(monkeypatch):
    made = {}

    class FakeOpenAI:
        def __init__(self, **kw):
            made.update(kw)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    OpenAIImages("m")
    assert made == {"max_retries": 0}


def test_an_error_is_recorded_without_its_message():
    class APIStatusError(Exception):
        status_code = 403
        request_id = "req_abc123"
        body = {"error": {"message": "Organization org-Secret42 must be verified",
                          "type": "invalid_request_error", "code": "org-Secret42"}}
    fields = model_error_fields(APIStatusError("Organization org-Secret42 must be verified"))
    assert fields == {"class": "APIStatusError", "status": 403, "request_id": "req_abc123",
                      "type": "invalid_request_error"}


@pytest.fixture
def spec(tmp_path):
    (tmp_path / "runs" / "t").mkdir(parents=True)
    (tmp_path / "runs" / "t" / "spec.toml").write_text(SPEC)
    return run.load("t", tmp_path), tmp_path


quiet = lambda *a: None


def saved(spec, root):
    return [r for r in run.requests(spec, root).values() if r["state"] == "saved"]


def test_a_run_plans_breadth_first_records_resumes_and_finishes(spec):
    spec, root = spec
    jobs = run.plan(spec)
    assert len(jobs) == 8
    assert [j.id for j in jobs[:2]] == ["whole-ebgi-F-01", "ornament-ebgi-F-01"]
    run.execute(spec, {"fake": fake_adapter}, go=False, root=root, log=quiet)
    assert run.events(spec, root) == []
    assert Image.open(root / "out/runs/t/inputs/W-canvas.png").size == (384, 256)

    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    assert [e["event"] for e in run.events(spec, root)[:3]] == ["sent", "returned", "saved"]
    recs = saved(spec, root)
    assert len(recs) == 8
    orn = next(r for r in recs if r["route"] == "ornament")
    assert orn["model"] == "ebgi-2026-10-30" and orn["terms"] == "Test terms."
    assert {"canvas", "editable", "refs", "block", "box"} <= set(orn["inputs"])
    assert run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet) == []

    rows = run.finish(spec, root)
    assert len(rows) == 8 and all(r["path_bytes"] > 0 for r in rows)
    svg = (root / "out/runs/t/finished" / f"{orn['id']}.svg").read_text()
    assert "Spectral SemiBold" in svg and "Test terms." in svg
    # the kept letter's own outline, and the cuts grown from it, so a Draft shows the letter alone
    cuts = re.findall(r'<path class="initial-cut[^"]*"[^>]*>', svg)
    outline = [c for c in cuts if "initial-outline" in c]
    assert len(outline) == 1 and 'vector-effect="non-scaling-stroke"' in outline[0]
    grown = [c for c in cuts if c not in outline]
    assert grown and all("initial-growth" in c and 'vector-effect="non-scaling-stroke"' in c for c in grown)
    whole = next(r for r in recs if r["route"] == "whole")
    plain = (root / "out/runs/t/finished" / f"{whole['id']}.svg").read_text()
    assert "initial-outline" not in plain and "initial-growth" not in plain and 'class="initial-cut"' in plain


def test_the_kept_letter_must_be_the_one_sent(spec):
    spec, root = spec
    spec["routes"], spec["letters"], spec["attempts"] = ["ornament"], "F", 1
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    (rec,) = saved(spec, root)
    out = root / "out/runs/t"
    assert run.letter_outline(out, rec, (1000, 1000))
    cap = rec["inputs"]["cap"]
    for changed in (0.6, cap + 0.003):  # a small change in the letter is still a different letter
        rec["inputs"]["cap"] = changed
        with pytest.raises(SystemExit):
            run.letter_outline(out, rec, (1000, 1000))
    # a halo wide enough to differ on the fixture's 256 px canvas (10 and 11 units draw the same)
    rec["inputs"]["cap"], rec["inputs"]["grow"] = cap, rec["inputs"]["grow"] + 5
    with pytest.raises(SystemExit):
        run.letter_outline(out, rec, (1000, 1000))


def test_finishing_uses_the_inputs_sent_not_the_spec_as_it_is_now(spec):
    spec, root = spec
    spec["routes"], spec["letters"], spec["attempts"] = ["ornament"], "F", 1
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    before = (run.finish(spec, root)[0], )
    spec["letter"]["grow"], spec["letter"]["weight"] = 30, "Bold"
    assert run.finish(spec, root)[0] == before[0]
    (rec,) = saved(spec, root)
    kept = root / "out/runs/t/inputs/sha256" / f"{rec['inputs']['editable']}.png"
    Image.new("1", Image.open(kept).size, 1).save(kept)
    with pytest.raises(SystemExit):
        run.finish(spec, root)


class HTTPError(Exception):
    status_code = 400


def raising(e):
    def adapter(model, **params):
        def call(req):
            raise e
        return call
    return adapter


def test_an_answered_error_is_recorded_stops_the_run_and_is_planned_again(spec):
    spec, root = spec
    with pytest.raises(HTTPError):
        run.execute(spec, {"fake": raising(HTTPError("org-Secret42 said no"))}, go=True,
                    root=root, log=quiet)
    (rec,) = run.requests(spec, root).values()
    assert rec["state"] == "failed" and rec["error"] == {"class": "HTTPError", "status": 400}
    assert "Secret42" not in (root / "runs/t/records.jsonl").read_text()
    spec["max_requests"] = 9
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    assert len(saved(spec, root)) == 8


def test_a_timeout_leaves_the_outcome_unknown_until_abandoned(spec):
    spec, root = spec
    spec["max_requests"] = 9
    with pytest.raises(TimeoutError):
        run.execute(spec, {"fake": raising(TimeoutError("read timed out"))}, go=True,
                    root=root, log=quiet)
    (rec,) = run.requests(spec, root).values()
    assert rec["state"] == "unknown" and rec["error"] == {"class": "TimeoutError"}
    with pytest.raises(SystemExit, match="outcome is unknown"):
        run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    assert [e["event"] for e in run.events(spec, root)] == ["sent", "unknown"]
    run.execute(spec, {"fake": fake_adapter}, go=True, abandon=True, root=root, log=quiet)
    states = [r["state"] for r in run.requests(spec, root).values()]
    assert states.count("abandoned") == 1 and states.count("saved") == 8


def test_a_negative_limit_is_refused_before_anything_is_done(spec):
    spec, root = spec
    with pytest.raises(SystemExit, match="--limit"):
        run.execute(spec, {"fake": fake_adapter}, go=True, limit=-1, root=root, log=quiet)
    assert run.events(spec, root) == [] and not (root / "out").exists()


def test_a_picture_that_cannot_be_read_is_still_accounted_for(spec):
    spec, root = spec
    spec["max_requests"] = 8

    def garbled(model, **params):
        return lambda req: Result(b"not a picture", request_id="req_x", seconds=0.0)
    with pytest.raises(Exception):
        run.execute(spec, {"fake": garbled}, go=True, root=root, log=quiet)
    assert [e["event"] for e in run.events(spec, root)] == ["sent", "returned", "failed"]
    (rec,) = run.requests(spec, root).values()
    assert rec["request_id"] == "req_x"
    # it counts against the ceiling, and its job is planned again
    with pytest.raises(SystemExit):
        run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)


def test_a_request_never_heard_of_again_stops_the_run_until_abandoned(spec):
    spec, root = spec

    def vanishing(model, **params):
        def gone(req):
            raise KeyboardInterrupt  # the process stops between sending and hearing back
        return gone
    with pytest.raises(KeyboardInterrupt):
        run.execute(spec, {"fake": vanishing}, go=True, limit=1, root=root, log=quiet)
    with pytest.raises(SystemExit, match="never heard of again"):
        run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    run.execute(spec, {"fake": fake_adapter}, go=True, abandon=True, root=root, log=quiet)
    states = [r["state"] for r in run.requests(spec, root).values()]
    assert states.count("abandoned") == 1 and states.count("saved") == 8


def test_a_returned_picture_on_disk_is_not_asked_for_again(spec):
    spec, root = spec
    spec["routes"], spec["letters"], spec["attempts"] = ["whole"], "F", 1
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    f = root / "runs/t/records.jsonl"
    f.write_text("".join(line + "\n" for line in f.read_text().splitlines()[:2]))  # lost "saved"
    assert run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet) == []
    assert [e["event"] for e in run.events(spec, root)] == ["sent", "returned", "saved"]


def test_a_run_will_not_pass_its_request_ceiling(spec):
    spec, root = spec
    spec["max_requests"] = 3
    with pytest.raises(SystemExit):
        run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    assert run.events(spec, root) == []


def test_a_picture_that_is_not_the_recorded_one_is_refused(spec):
    spec, root = spec
    spec["routes"], spec["letters"], spec["attempts"] = ["whole"], "F", 1
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    (rec,) = saved(spec, root)
    Image.new("L", (256, 256), 0).save(root / "out/runs/t" / rec["output"]["file"])
    with pytest.raises(SystemExit):
        run.finish(spec, root)
