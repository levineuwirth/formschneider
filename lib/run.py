"""A run of the trial: its spec, the jobs it plans, the record of every
request made for it, and the finishing of what came back.

runs/NAME/spec.toml (in git) says what is asked of whom: letters,
attempts, routes, models and their settings, prompts, references, the
kept letter. runs/NAME/records.jsonl (in git) is an append-only log of
events, each naming its request:

  sent      before the request goes out, flushed to disk: what is sent
            (prompt, settings, a checksum of every input), the terms, when
  returned  as soon as the provider answers, before the picture is touched:
            request id, usage, time taken, the returned bytes' checksum
  saved     the picture written to out/ and read back
  failed    the provider answered with an error (an HTTP status), or what
            followed a returned picture failed: allowlisted fields only
            (model.error_fields), never the message
  unknown   the request failed with no answer from the provider (a timeout,
            a lost connection): whether it was done, and billed, is unknown
  abandoned the author's decision about a request whose outcome is unknown,
            sent and never heard of or ended in a timeout (--abandon)

So every request is on record before it costs anything, and a run that
stops anywhere can be resumed without silently repeating one. Nothing in
the log can be worked out again later, which is why it is kept and the
rest is not. Every input sent is kept in out/runs/NAME/inputs/ under its
checksum, and the pictures in out/runs/NAME/images/; the checksums in the
log say whether a file is the one sent or made.
"""

import datetime
import hashlib
import io
import json
import math
import os
import subprocess
import tomllib
import uuid
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path as File

import numpy as np
from PIL import Image

from bench import contact
from canvas import Layout, halo_view, letter_canvas, png, put_back, references, registration
from finish import BUDGET, FINISH, crop_to_ink, fitted, measures, traced
from fonts import EBGI, SPECTRAL
from initial import initial_svg, measure
from letter import capital
from model import NotSent, Request, error_fields
from paths import Path, fmt
from raster import bare_svg, rasterize
from simplify import simplify

ROOT = File(__file__).resolve().parent.parent
ROUTES = ("whole", "ornament")


@dataclass(frozen=True)
class Job:
    route: str
    provider: str
    model: str      # the provider's id, dated where the provider dates them
    name: str       # the spec's short name for it, used in ids
    letter: str
    attempt: int

    @property
    def id(self) -> str:
        return f"{self.route}-{self.name}-{self.letter}-{self.attempt:02d}"


def load(name: str, root: File = ROOT) -> dict:
    spec = tomllib.loads((root / "runs" / name / "spec.toml").read_text())
    spec["name"] = name
    return spec


def plan(spec: dict) -> list[Job]:
    """Breadth first: every route and letter once before any second attempt,
    so a run cut short by --limit has sampled all of them."""
    assert set(spec["routes"]) <= set(ROUTES), spec["routes"]
    return [Job(route, m["provider"], m["model"], m.get("name", m["model"]), c, k)
            for k in range(1, spec["attempts"] + 1) for c in spec["letters"]
            for m in spec["model"] for route in spec["routes"]]


def events(spec: dict, root: File = ROOT) -> list[dict]:
    f = root / "runs" / spec["name"] / "records.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines() if line] if f.exists() else []


def requests(spec: dict, root: File = ROOT) -> dict[str, dict]:
    """Each request's events folded into one record, its state the last event."""
    out: dict[str, dict] = {}
    for e in events(spec, root):
        r = out.setdefault(e["request"], {})
        r.update({k: v for k, v in e.items() if k not in ("event", "at")})
        r["state"] = e["event"]
        r.setdefault("at", {})[e["event"]] = e["at"]
    return out


def _log(spec: dict, root: File, event: str, request: str, **fields) -> None:
    rec = {"event": event, "request": request,
           "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"), **fields}
    with open(root / "runs" / spec["name"] / "records.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


_EXTENSIONS = {"JPEG": "jpg"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _keep(out: File, img: Image.Image) -> str:
    """Keep an input under its checksum, as the bytes that are sent."""
    data = png(img)
    digest = _sha(data)
    f = out / "inputs" / "sha256" / f"{digest}.png"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    return digest


def _kept(out: File, digest: str) -> Image.Image:
    f = out / "inputs" / "sha256" / f"{digest}.png"
    if not f.exists() or _sha(f.read_bytes()) != digest:
        raise SystemExit(f"input {digest[:12]}… is missing or not the one sent")
    return Image.open(f)


def _code() -> dict:
    """Which code made the request: the commit, whether the tree had changes
    not in it, and the versions of the providers' client libraries."""
    from importlib import metadata

    def git(*a):
        r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    packages = {}
    for p in ("openai", "fal-client", "httpx"):
        try:
            packages[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            pass
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status),
            "packages": packages}


# where each kind of token is in a usage, for a model priced per million tokens
_TOKENS = {"text_input": ("input_tokens_details", "text_tokens"),
           "image_input": ("input_tokens_details", "image_tokens"),
           "text_output": ("output_tokens_details", "text_tokens"),
           "image_output": ("output_tokens_details", "image_tokens")}


def usd(usage: dict | None, rates: dict | None, per_unit: float | None = None) -> float | None:
    """What a request cost by its usage at the prices the spec records: USD
    per million tokens (`rates`, OpenAI's usage), or USD per billable unit
    (`per_unit`, the units fal reports for a request). None when the usage
    or the price is missing, or a kind of token used has no rate."""
    if usage and per_unit is not None and usage.get("billable_units") is not None:
        try:
            return round(float(usage["billable_units"]) * per_unit, 6)
        except (TypeError, ValueError):
            return None
    if not usage or not rates:
        return None
    total = 0.0
    for kind, (group, key) in _TOKENS.items():
        n = (usage.get(group) or {}).get(key) or 0
        if n and kind not in rates:
            return None
        total += n * rates.get(kind, 0) / 1e6
    return round(total, 6)


def _model(spec: dict, job: Job) -> dict:
    return next(m for m in spec["model"] if m["model"] == job.model and m["provider"] == job.provider)


def request(spec: dict, job: Job, refs: list) -> tuple[Request, Layout | None]:
    """What the job sends: for the ornament route the kept letter on its
    canvas, with where the model may draw."""
    m, k = _model(spec, job), spec["letter"]
    path, box = capital(SPECTRAL.format(weight=k["weight"]), job.letter, cap=k["cap"])
    # the provider's size nearest the block's shape, so a wide letter's
    # block is drawn wide and not cropped out of a square
    size = tuple(min(m["sizes"], key=lambda s: abs(math.log(s[0] / s[1] * box[1] / box[0]))))
    fill = k.get("fill", False)
    if fill and size[0] * box[1] > size[1] * box[0]:
        # the block widened to the canvas, so the model's ornament runs to the
        # canvas's edges and none of it is cropped off at the block's
        path, box = capital(SPECTRAL.format(weight=k["weight"]), job.letter, cap=k["cap"],
                            width=round(box[1] * size[0] / size[1]))
    prompt = spec["prompt"][job.route].format(letter=job.letter)
    # a model that takes few images takes the first references, the canvas
    # counting as one; a seed follows from the job, so a retry repeats it
    room = m.get("max_images", 1 + len(refs))
    seed = zlib.crc32(job.id.encode()) & 0x7FFFFFFF if m.get("seeded") else None
    if job.route == "whole":
        return Request(prompt, size, refs=refs[:room], seed=seed), None
    canvas, editable, lay = letter_canvas(path, box, size, k["grow"], fill)
    return Request(prompt, size, canvas, editable, refs[:room - 1], seed=seed), lay


def _reconcile(spec: dict, root: File, out: File) -> None:
    """A request that returned but was never marked saved (the run stopped
    in between) is marked saved if its picture is on disk and is the one
    returned; otherwise it stays as it is, accounted for and not done."""
    for key, r in requests(spec, root).items():
        if r["state"] != "returned":
            continue
        for f in sorted((out / "images").glob(f"{r['id']}.*")):
            if _sha(f.read_bytes()) == r["sha256"]:
                _log(spec, root, "saved", key, output={"file": f"images/{f.name}",
                                                       "sha256": r["sha256"],
                                                       "size": list(Image.open(f).size)})
                break


def execute(spec: dict, adapters: dict, go: bool = False, limit: int | None = None,
            abandon: bool = False, root: File = ROOT, out: File | None = None,
            log=print) -> list[Job]:
    """Make the run's outstanding requests, or, without go, only say what
    they would be and write their inputs out for looking at."""
    if limit is not None and limit < 0:
        raise SystemExit(f"--limit must be 0 or more, not {limit}")
    out = out or root / "out" / "runs" / spec["name"]
    _reconcile(spec, root, out)
    reqs = requests(spec, root)
    lost = {k: r for k, r in reqs.items() if r["state"] in ("sent", "unknown")}
    if lost and not abandon:
        raise SystemExit(f"{len(lost)} request(s) were sent and their outcome is unknown "
                         "(never heard of again, a timeout, or a lost connection): "
                         + ", ".join(r["id"] for r in lost.values())
                         + ". They may have been done and billed. Check the provider's usage, "
                         "then run again with --abandon to record that and plan them again.")
    if lost and go:
        for k in lost:
            _log(spec, root, "abandoned", k)
        reqs = requests(spec, root)
    made = {r["id"] for r in reqs.values() if r["state"] == "saved"}
    todo = [j for j in plan(spec) if j.id not in made][:limit]
    if len(reqs) + len(todo) > spec["max_requests"]:
        raise SystemExit(f"{len(reqs)} requests made and {len(todo)} to make: over the run's "
                         f"max_requests ({spec['max_requests']})")
    refs = references(EBGI, spec["refs"]["letters"])
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    for name, img in refs:
        img.save(out / "inputs" / f"ref-{name}.png")
    est = sum(_model(spec, j).get("est_usd", 0) for j in todo)
    log(f"{spec['name']}: {len(made)} made, {len(todo)} to make, about ${est:.2f} by the spec's estimates")
    for j in todo:
        req, _ = request(spec, j, refs)
        if req.image is not None:
            req.image.save(out / "inputs" / f"{j.letter}-canvas.png")
            halo_view(req.image, req.editable).save(out / "inputs" / f"{j.letter}-halo.png")
        log(f"  {j.id}")
    if not go:
        log("planned only; nothing was sent (--go sends)")
        return todo
    (out / "images").mkdir(exist_ok=True)
    callers, code = {}, _code()
    crop = spec.get("finish", {}).get("crop")
    for j in todo:
        m = _model(spec, j)
        if (j.provider, j.model) not in callers:
            callers[j.provider, j.model] = adapters[j.provider](j.model, **m.get("params", {}))
        req, lay = request(spec, j, refs)
        inputs = {"refs": {n: _keep(out, i) for n, i in req.refs}}
        if req.image is not None:
            inputs |= {"canvas": _keep(out, req.image),
                       "editable": _keep(out, Image.fromarray(req.editable)),
                       "letter": f"Spectral {spec['letter']['weight']}",
                       "cap": spec["letter"]["cap"], "grow": spec["letter"]["grow"],
                       "block": list(lay.block), "box": list(lay.box),
                       **({"fill": True} if spec["letter"].get("fill") else {})}
        key = uuid.uuid4().hex
        _log(spec, root, "sent", key, id=j.id, **asdict(j), run=spec["name"], prompt=req.prompt,
             size=list(req.size), params=m.get("params", {}), inputs=inputs,
             terms=m.get("terms"), est_usd=m.get("est_usd"), usd_per_mtok=m.get("usd_per_mtok"),
             usd_per_unit=m.get("usd_per_unit"),
             seed=req.seed, code=code,
             **({"crop": crop} if crop and j.route == "whole" else {}))
        try:
            res = callers[j.provider, j.model](req)
        except Exception as e:  # recorded, and the run stops: the next would likely fail too
            # an HTTP status means the provider answered; anything else (a
            # timeout, a lost connection) leaves the outcome unknown
            fields = error_fields(e)
            known = "status" in fields or isinstance(e, NotSent)
            _log(spec, root, "failed" if known else "unknown", key, error=fields)
            raise
        _log(spec, root, "returned", key, request_id=res.request_id, seconds=res.seconds,
             usage=res.usage, usd=usd(res.usage, m.get("usd_per_mtok"), m.get("usd_per_unit")),
             meta=res.meta,
             bytes=len(res.png), sha256=_sha(res.png))
        try:  # the bytes as they came, named for what they are: not every model can send a PNG
            pic = Image.open(io.BytesIO(res.png))
            name = f"images/{j.id}.{_EXTENSIONS.get(pic.format, pic.format.lower())}"
            (out / name).write_bytes(res.png)
        except Exception as e:
            _log(spec, root, "failed", key, error=error_fields(e))
            raise
        _log(spec, root, "saved", key, output={"file": name, "sha256": _sha(res.png),
                                               "size": list(pic.size)})
        log(f"  {j.id}: saved, {res.seconds}s")
    return todo


def picture(out: File, r: dict) -> Image.Image:
    """A saved request's picture as finishing takes it, checked against the
    record, with the letter put back (ornament route) from the inputs kept
    when it was sent."""
    data = (out / r["output"]["file"]).read_bytes()
    if _sha(data) != r["output"]["sha256"]:
        raise SystemExit(f"{r['id']}: the picture is not the one the record says was made")
    gray = Image.open(io.BytesIO(data)).convert("L")
    if r.get("crop") == "ink":
        gray = crop_to_ink(gray)
    elif r.get("crop"):
        raise SystemExit(f"{r['id']}: no such crop as {r['crop']!r}")
    if r["route"] == "ornament":
        i = r["inputs"]
        canvas = _kept(out, i["canvas"]).convert("L")
        editable = np.asarray(_kept(out, i["editable"])).astype(bool)
        gray = put_back(gray, canvas, editable, Layout(tuple(r["size"]), tuple(i["block"]),
                                                       tuple(i["box"])))
    return gray


def letter_registration(out: File, r: dict) -> dict:
    """For an ornament-only initial, how the model's own picture of the
    letter sat on the kept one (canvas.registration), from the picture and
    the canvas kept when it was sent, both checked. Empty for a whole one."""
    if r["route"] != "ornament":
        return {}
    data = (out / r["output"]["file"]).read_bytes()
    if _sha(data) != r["output"]["sha256"]:
        raise SystemExit(f"{r['id']}: the picture is not the one the record says was made")
    i = r["inputs"]
    return registration(Image.open(io.BytesIO(data)), _kept(out, i["canvas"]).convert("L"),
                        Layout(tuple(r["size"]), tuple(i["block"]), tuple(i["box"])), i["grow"])


def letter_outline(out: File, r: dict, box: tuple[int, int]) -> Path | None:
    """The kept capital's own outline (ornament route) in the cut's frame,
    as it was sent: from the font, cap height and halo the record names,
    its canvas and halo drawn again as they were made and required to be
    the ones sent, pixel for pixel. None for a drawn letter."""
    if r["route"] != "ornament":
        return None
    i = r["inputs"]
    family, weight = i["letter"].rsplit(" ", 1)
    if family != "Spectral":
        raise SystemExit(f"{r['id']}: no font for the kept letter {i['letter']}")
    fill = i.get("fill", False)
    path, lbox = capital(SPECTRAL.format(weight=weight), r["letter"], height=i["box"][1], cap=i["cap"],
                         width=i["box"][0] if fill else 0)
    sent = np.asarray(_kept(out, i["canvas"]).convert("L"))
    free = np.asarray(_kept(out, i["editable"])).astype(bool)
    again, editable, lay = letter_canvas(path, lbox, tuple(r["size"]), i["grow"], fill)
    if (list(lbox) != list(i["box"]) or list(lay.block) != list(i["block"])
            or not np.array_equal(np.asarray(again), sent) or not np.array_equal(editable, free)):
        raise SystemExit(f"{r['id']}: the kept letter drawn again is not the canvas sent "
                         "(its settings, the font, or the renderer differ)")
    kx, ky = box[0] / lbox[0], box[1] / lbox[1]
    return [[(op, tuple((x * kx, y * ky) for x, y in pts)) for op, pts in sub] for sub in path]


def finish(spec: dict, root: File = ROOT, out: File | None = None) -> list[dict]:
    """Every picture the run has made, through the fixed finishing: the
    letter put back (ornament route) from the inputs kept when it was sent,
    cropped to its block, cut, written as the site would hold it, measured,
    and laid out on a contact sheet; and cut again fitted to the budget
    (finished/fitted/), with the tolerance the fit took. Everything comes
    from the record and the files it names, checked; nothing from the spec
    as it is now."""
    out = out or root / "out" / "runs" / spec["name"]
    (out / "finished").mkdir(parents=True, exist_ok=True)
    rows, cells = [], {}
    for r in (r for r in requests(spec, root).values() if r["state"] == "saved"):
        gray = picture(out, r)
        raw, box = traced(gray)
        letter = letter_outline(out, r, box)
        path = simplify(raw, FINISH["tolerance"])
        svg = initial_svg(path, box, credit(spec, r), letter)
        (out / "finished" / f"{r['id']}.svg").write_text(svg)
        fit, t = fitted(raw)
        fit_svg = initial_svg(fit, box, credit(spec, r, FINISH | {"tolerance": t}), letter)
        (out / "finished" / "fitted").mkdir(exist_ok=True)
        (out / "finished" / "fitted" / f"{r['id']}.svg").write_text(fit_svg)
        fit_bytes = measure(fit, fit_svg)["path_bytes"]
        row = {"id": r["id"], "route": r["route"], "model": r["model"], "letter": r["letter"],
               "attempt": r["attempt"], **measures(gray, path, box, svg), "box": list(box),
               "outline_bytes": len(fmt(letter)) if letter else 0,
               "fit_tolerance": t, "fit_path_bytes": fit_bytes,
               "fit_budget": round(fit_bytes / BUDGET, 3), **letter_registration(out, r)}
        rows.append(row)
        cells.setdefault(r["letter"], []).append(
            (f"{r['route'][0]}{r['attempt']} {row['path_bytes'] / 1000:.0f} KB ×{row['budget']:.1f}",
             rasterize(bare_svg(path, box), 600)))
    rows.sort(key=lambda row: row["id"])
    (out / "finished" / "measures.json").write_text(json.dumps(rows, indent=1))
    if cells:
        contact([(c, cells[c]) for c in sorted(cells)], cell=200).save(out / "finished" / "sheet.png")
    return rows


def credit(spec: dict, r: dict, finish: dict = FINISH) -> str:
    who = f"{r['model']} ({r['provider']})"
    what = (f"ornament drawn by {who} around {r['inputs']['letter']}'s capital "
            f"(SIL Open Font License 1.1)" if r["route"] == "ornament" else f"drawn by {who}")
    return (f"{r['letter']}, {what}; formschneider {spec['name']}/{r['id']}, "
            f"{r['at']['sent'][:10]}. {r.get('terms') or ''} "
            f"Cut: {', '.join(f'{k} {v}' for k, v in finish.items())}"
            f"{', cropped to its ink' if r.get('crop') == 'ink' else ''}.").replace("--", "–")
