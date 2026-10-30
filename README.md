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
be met when the cut is given a clean picture; what is left to find out
is what the models give it.

## Running

Python 3.12 or later through [uv](https://docs.astral.sh/uv/), with
`potrace` and `rsvg-convert` from the system, and EB Garamond Initials
(TeX Live's path by default; set `FORMSCHNEIDER_EBGI` to override it).

```sh
make test        # the cut against known outlines
make calibrate   # out/calibrate/: results.md, results.json, sheet.png, svg/
```

## License

The code is MIT (`LICENSE`). Fonts are not copied into the repository.
A generated initial carries its own terms, recorded with it, which
depend on the model that drew it.
