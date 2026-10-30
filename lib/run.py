"""A run of the trial: its spec, the jobs it plans, the record of every
request made for it, and the finishing of what came back.

runs/NAME/spec.toml (in git) says what is asked of whom: letters,
attempts, routes, models and their settings, prompts, references, the
kept letter. runs/NAME/records.jsonl (in git) gets one line per request
as it returns, ok or not: what was sent (prompt, settings, checksums of
every input), what came back (request id, usage, checksum of the
picture), the provider's terms, and when. Nothing in it can be worked out
again later, which is why it is kept and the rest is not. Pictures, their
inputs and everything finished from them go to out/runs/NAME/, outside
git; the checksums in the record say whether a picture is the one made.
"""

import datetime
import hashlib
import io
import json
import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path as File

from PIL import Image

from bench import contact
from canvas import Layout, letter_canvas, png, put_back, references
from finish import FINISH, cut, measures
from fonts import EBGI, SPECTRAL
from initial import initial_svg
from letter import capital
from model import Request
from raster import bare_svg, rasterize

ROOT = File(__file__).resolve().parent.parent
ROUTES = ("whole", "ornament")


@dataclass(frozen=True)
class Job:
    route: str
    provider: str
    model: str
    letter: str
    attempt: int

    @property
    def id(self) -> str:
        return f"{self.route}-{self.model}-{self.letter}-{self.attempt:02d}"


def load(name: str, root: File = ROOT) -> dict:
    spec = tomllib.loads((root / "runs" / name / "spec.toml").read_text())
    spec["name"] = name
    return spec


def plan(spec: dict) -> list[Job]:
    assert set(spec["routes"]) <= set(ROUTES), spec["routes"]
    return [Job(route, m["provider"], m["model"], c, k)
            for m in spec["model"] for route in spec["routes"]
            for c in spec["letters"] for k in range(1, spec["attempts"] + 1)]


def records(spec: dict, root: File = ROOT) -> list[dict]:
    f = root / "runs" / spec["name"] / "records.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines() if line] if f.exists() else []


def _append(spec: dict, rec: dict, root: File) -> None:
    with open(root / "runs" / spec["name"] / "records.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _model(spec: dict, job: Job) -> dict:
    return next(m for m in spec["model"] if m["model"] == job.model and m["provider"] == job.provider)


def request(spec: dict, job: Job, refs: list) -> tuple[Request, Layout | None, Image.Image | None]:
    """What the job sends: for the ornament route the kept letter on its
    canvas, with where the model may draw."""
    m, k = _model(spec, job), spec["letter"]
    path, box = capital(SPECTRAL.format(weight=k["weight"]), job.letter, cap=k["cap"])
    # the provider's size nearest the block's shape, so a wide letter's
    # block is drawn wide and not cropped out of a square
    size = tuple(min(m["sizes"], key=lambda s: abs(math.log(s[0] / s[1] * box[1] / box[0]))))
    prompt = spec["prompt"][job.route].format(letter=job.letter)
    if job.route == "whole":
        return Request(prompt, size, refs=refs), None, None
    canvas, editable, lay = letter_canvas(path, box, size, k["grow"])
    return Request(prompt, size, canvas, editable, refs), lay, canvas


def execute(spec: dict, adapters: dict, go: bool = False, limit: int | None = None,
            root: File = ROOT, out: File | None = None, log=print) -> list[Job]:
    """Make the run's outstanding requests, or, without go, only say what
    they would be and write their inputs out for looking at."""
    out = out or root / "out" / "runs" / spec["name"]
    recs = records(spec, root)
    made = {r["id"] for r in recs if r["status"] == "ok"}
    todo = [j for j in plan(spec) if j.id not in made][:limit]
    if len(recs) + len(todo) > spec["max_requests"]:
        raise SystemExit(f"{len(recs)} requests made and {len(todo)} to make: over the run's "
                         f"max_requests ({spec['max_requests']})")
    refs = references(EBGI, spec["refs"]["letters"])
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    for name, img in refs:
        img.save(out / "inputs" / f"ref-{name}.png")
    est = sum(_model(spec, j).get("est_usd", 0) for j in todo)
    log(f"{spec['name']}: {len(made)} made, {len(todo)} to make, about ${est:.2f} by the spec's estimates")
    for j in todo:
        req, _, canvas = request(spec, j, refs)
        if canvas is not None:
            canvas.save(out / "inputs" / f"{j.letter}-canvas.png")
            Image.fromarray(req.editable).save(out / "inputs" / f"{j.letter}-editable.png")
        log(f"  {j.id}")
    if not go:
        log("planned only; nothing was sent (--go sends)")
        return todo
    (out / "images").mkdir(exist_ok=True)
    callers = {}
    for j in todo:
        m = _model(spec, j)
        if (j.provider, j.model) not in callers:
            callers[j.provider, j.model] = adapters[j.provider](j.model, **m.get("params", {}))
        req, lay, canvas = request(spec, j, refs)
        rec = {"id": j.id, **asdict(j), "run": spec["name"], "prompt": req.prompt,
               "size": list(req.size), "params": m.get("params", {}),
               "inputs": {"refs": {n: _sha(png(i)) for n, i in refs}},
               "terms": m.get("terms"), "est_usd": m.get("est_usd"),
               "requested": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")}
        if canvas is not None:
            rec["inputs"] |= {"canvas": _sha(png(canvas)),
                              "editable": _sha(png(Image.fromarray(req.editable))),
                              "letter": f"Spectral {spec['letter']['weight']}",
                              "cap": spec["letter"]["cap"], "grow": spec["letter"]["grow"],
                              "block": list(lay.block)}
        try:
            res = callers[j.provider, j.model](req)
        except Exception as e:  # recorded, and the run stops: the next would likely fail too
            _append(spec, rec | {"status": "error", "error": f"{type(e).__name__}: {e}"[:800]}, root)
            raise
        (out / "images" / f"{j.id}.png").write_bytes(res.png)
        size = Image.open(io.BytesIO(res.png)).size
        _append(spec, rec | {"status": "ok", "request_id": res.request_id, "seconds": res.seconds,
                             "usage": res.usage, "meta": res.meta,
                             "output": {"file": f"images/{j.id}.png", "sha256": _sha(res.png),
                                        "size": list(size)}}, root)
        log(f"  {j.id}: ok, {res.seconds}s")
    return todo


def finish(spec: dict, root: File = ROOT, out: File | None = None) -> list[dict]:
    """Every picture the run has made, through the fixed finishing: the
    letter put back (ornament route), cropped to its block, cut, written as
    the site would hold it, measured, and laid out on a contact sheet."""
    out = out or root / "out" / "runs" / spec["name"]
    (out / "finished").mkdir(parents=True, exist_ok=True)
    rows, cells = [], {}
    for r in (r for r in records(spec, root) if r["status"] == "ok"):
        data = (out / r["output"]["file"]).read_bytes()
        if _sha(data) != r["output"]["sha256"]:
            raise SystemExit(f"{r['id']}: the picture is not the one the record says was made")
        gray = Image.open(io.BytesIO(data)).convert("L")
        job = Job(r["route"], r["provider"], r["model"], r["letter"], r["attempt"])
        if job.route == "ornament":
            req, lay, canvas = request(spec, job, [])
            gray = put_back(gray, canvas, req.editable, lay)
        path, box = cut(gray)
        svg = initial_svg(path, box, credit(spec, r))
        (out / "finished" / f"{r['id']}.svg").write_text(svg)
        row = {"id": r["id"], "route": r["route"], "model": r["model"], "letter": r["letter"],
               "attempt": r["attempt"], **measures(gray, path, box, svg)}
        rows.append(row)
        cells.setdefault(r["letter"], []).append(
            (f"{r['route'][0]}{r['attempt']} {row['path_bytes'] / 1000:.0f} KB ×{row['budget']:.1f}",
             rasterize(bare_svg(path, box), 600)))
    (out / "finished" / "measures.json").write_text(json.dumps(rows, indent=1))
    if cells:
        contact([(c, cells[c]) for c in spec["letters"] if c in cells], cell=200).save(
            out / "finished" / "sheet.png")
    return rows


def credit(spec: dict, r: dict) -> str:
    who = f"{r['model']} ({r['provider']})"
    what = (f"ornament drawn by {who} around Spectral {spec['letter']['weight']}'s capital "
            f"(SIL Open Font License 1.1)" if r["route"] == "ornament" else f"drawn by {who}")
    return (f"{r['letter']}, {what}; formschneider {spec['name']}/{r['id']}, "
            f"{r['requested'][:10]}. {r.get('terms') or ''} Cut: {FINISH}.").replace("--", "–")
