# formschneider

A *Formschneider* cut the woodblock from a drawing someone else had made.
This repository does that job for ornamental initials: image models
draw, and formschneider cuts what they draw into outlines that
[levineuwirth.org](https://levineuwirth.org) can draw in, shade and ink.
It is also the bench for a matched trial of those models, whose write-up
will live on the site.

## The trial

Two routes to a machine-made initial are compared on the same six
letters (A, F, I, O, S, W), the same style references and the same
number of attempts, and each result goes through the same cut:

- **whole initial**: the model draws letter and ornament together;
- **ornament only**: the letter is Spectral's capital, fixed and
  masked, and the model draws only the ground around it.

Each is measured four ways: whether the letter is right, whether the six
read as one set, what the outlines cost against EB Garamond Initials'
own, and how many attempts it takes to get one worth keeping. Rinceau
(vine scrolls on open ground, EB Garamond Initials' own idiom) comes
first; criblé (a dotted ground) second. Every generated picture keeps
its provenance (model, version, date, prompt, seed, mask, cost and terms)
from the moment it is made.

## What the site takes

A set: a directory with one SVG per capital (`F.svg`), which a page
names in its frontmatter (`initials: /initials/eb-garamond`). Each SVG
holds its outlines three times, as a hairline shade, as cuts drawn in
one by one, and as the ink that fills them (`lib/initial.py`; the
site's `MARKS.md` §2.6 is the contract). `tests/test_cut.py` holds the
code to EB Garamond Initials' ten letters exactly as the site has them.

## Calibration

`make calibrate` draws EB Garamond Initials' A, F and O as pictures at
512, 1024 and 2048 px and traces them back over a grid of potrace's
settings. Each trace is scored on what it costs and on how much of the
original's ink it keeps (IoU at 1000 px). A clean picture of 1024 px or
more traces back at 1.0–1.2 times the original's path data with an IoU
of 0.98 (the F, with the finest vines, needs 2048 px). So the budget can
be met when the cut is given a clean picture.

## Scans

`make scans` tries the cut on real woodcut initials: nine scans from
Wikimedia Commons, recorded with their sources and licenses in
`corpus/scans.json` (`bin/corpus` adds and fetches them). They cover
rinceau at low resolution and in photographs of a page, criblé, dense
hatching and a black ground.

Traced as they are, real scans cost 4 to 60 times the budget. Most of
that is the wobble of a printed edge, which potrace follows faithfully.
So the cut refits each contour with fewer curves within a tolerance
(`lib/simplify.py`). Fidelity is measured as deviation, the 95th
percentile of distance between the trace's outline and the scan's in
both directions, in units of a thousand along the initial's long side.
An initial is shown at most about 230 device pixels tall, so 2 units is
under half a pixel.

Cost is then the scan's edge length, a fact of the design, times bytes
per unit of edge, a fact of the cut. With a refit within 2 units, the
cut spends 0.6 to 1.2 bytes per unit on rinceau. EB Garamond Initials' F,
drawn by hand, spends 0.62. What remains is edge length. The F has about
29,000 units of edge. The rinceau scans run from 33,000 to 80,000 and come
in at 1.1 to 5.5 times the budget. Criblé (94,000) comes in at 6 to 10
times, and hatching (116,000 to 134,000) at 10 to 22 times. The budget is
therefore a limit on how much edge an initial may have, and it can be
measured on a picture before anything is traced.

## Generating

A run is a directory under `runs/`. `spec.toml` says what is asked of
which models: letters, attempts, routes, sizes, prompts, references, and
the kept letter. Models are named by their dated snapshot, so every
request in a run goes to the same one. `records.jsonl` is an append-only
log of each request's events:

- **sent:** written to disk before the request goes out, with the prompt,
  the settings, a checksum of every input, the terms and the time;
- **returned:** the request id, usage, and the checksum of what came
  back, written before the picture is touched;
- **saved:** the picture written and read back;
- **failed:** the error's class, status, request id and provider code,
  but never its message, which can name an account.

The client never retries on its own, so every request is on record before
it can cost anything, and none is repeated silently. A request that was
sent and never heard of again stops the run until the author has checked
the provider's usage and passes `--abandon`. Requests go out breadth
first, so `--limit` samples every route and letter. Both files are in git.
The pictures, and every input under its checksum, go to `out/runs/NAME/`.
Finishing reads only the record and the files it names, checked, so
editing the spec after a run cannot change what the run's pictures are
finished with.

- **Ornament only:** Spectral SemiBold's capital is set in its block on a
  canvas of the provider's size, and the model may draw everywhere but the
  letter and a thin halo around it. Some providers honor a mask only
  loosely, so the letter and halo are put back from the canvas afterwards.
- **References:** EB Garamond Initials' D, G, L, N, Q and T, none of the
  trial's letters, so no reference can be copied.
- **Finishing:** every picture gets the same fixed finishing, the setting
  fixed on the scans before any generated picture was seen.

```sh
bin/generate pilot-openai        # plan only: what would be sent, and its inputs in out/
bin/generate pilot-openai --go --limit 4   # send four (keys from .env); stops at an error
bin/finish pilot-openai          # put back, cut, measure: out/runs/pilot-openai/finished/
```

## Running

Python 3.12 or later through [uv](https://docs.astral.sh/uv/), with
`potrace` and `rsvg-convert` from the system. The fonts come from the
sources `fonts.json` records, checked against its checksums: EB Garamond
Initials from CTAN, and Spectral from the Google Fonts revision
levineuwirth.org pins, so the kept letter is the one the site sets.

```sh
bin/fonts        # the fonts, into out/fonts/
make test        # the cut against known outlines
make calibrate   # out/calibrate/: results.md, results.json, sheet.png, svg/
bin/corpus fetch # the scans corpus/scans.json records, into out/corpus/
make scans       # out/scans/: the same, for the scans
uv run --extra openai bin/generate NAME   # see Generating
```

## CI

GitHub runs `make test` on every push (`.github/workflows/tests.yml`),
with the fonts from `bin/fonts` and the EB Garamond set from
levineuwirth.org's repository. A test that skips there fails the run.

## License

The code is MIT (`LICENSE`). Fonts are not copied into the repository.
A generated initial carries its own terms, recorded with it, which
depend on the model that drew it.
