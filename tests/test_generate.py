"""The generation side, with no model and no network: a fake adapter and a
fake OpenAI client stand in, so what is sent, what is recorded and what is
finished can be checked exactly."""

import base64
import json
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
model = "ebgi"
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


@pytest.fixture
def spec(tmp_path):
    (tmp_path / "runs" / "t").mkdir(parents=True)
    (tmp_path / "runs" / "t" / "spec.toml").write_text(SPEC)
    return run.load("t", tmp_path), tmp_path


def test_a_run_plans_records_resumes_and_finishes(spec):
    spec, root = spec
    quiet = lambda *a: None
    assert len(run.plan(spec)) == 8
    run.execute(spec, {"fake": fake_adapter}, go=False, root=root, log=quiet)
    assert run.records(spec, root) == []
    assert (root / "out/runs/t/inputs/W-canvas.png").exists()
    assert Image.open(root / "out/runs/t/inputs/W-canvas.png").size == (384, 256)

    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet)
    recs = run.records(spec, root)
    assert len(recs) == 8 and all(r["status"] == "ok" for r in recs)
    orn = next(r for r in recs if r["route"] == "ornament")
    assert {"canvas", "editable", "refs", "block"} <= set(orn["inputs"]) and orn["terms"] == "Test terms."
    assert run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=quiet) == []

    rows = run.finish(spec, root)
    assert len(rows) == 8 and all(r["path_bytes"] > 0 for r in rows)
    svg = (root / "out/runs/t/finished" / f"{orn['id']}.svg").read_text()
    assert "Spectral SemiBold" in svg and "Test terms." in svg and 'class="initial-cut"' in svg


def test_a_failed_request_is_recorded_and_stops_the_run(spec):
    spec, root = spec

    def broken(model, **params):
        def fail(req):
            raise RuntimeError("no")
        return fail
    with pytest.raises(RuntimeError):
        run.execute(spec, {"fake": broken}, go=True, root=root, log=lambda *a: None)
    (rec,) = run.records(spec, root)
    assert rec["status"] == "error" and "RuntimeError" in rec["error"]


def test_a_run_will_not_pass_its_request_ceiling(spec):
    spec, root = spec
    spec["max_requests"] = 3
    with pytest.raises(SystemExit):
        run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=lambda *a: None)
    assert run.records(spec, root) == []


def test_a_picture_that_is_not_the_recorded_one_is_refused(spec):
    spec, root = spec
    spec["routes"], spec["letters"], spec["attempts"] = ["whole"], "F", 1
    run.execute(spec, {"fake": fake_adapter}, go=True, root=root, log=lambda *a: None)
    (rec,) = run.records(spec, root)
    Image.new("L", (256, 256), 0).save(root / "out/runs/t" / rec["output"]["file"])
    with pytest.raises(SystemExit):
        run.finish(spec, root)
