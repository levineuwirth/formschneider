"""Outlines refit with fewer curves: each contour sampled, split at its
corners, and fit again with cubics that stray at most `tolerance` units
from it (Schneider, "An Algorithm for Automatically Fitting Digitized
Curves", Graphics Gems, 1990).

potrace follows every wobble a printed edge has; at the size an initial is
shown, a wobble of a unit or two in a thousand is not there to see, and
dropping it is most of what makes a scan dear.
"""

import math

import numpy as np

from paths import Path

CORNER = math.radians(10)  # potrace's smooth joins are exactly collinear


def _sample(p0, seg, step):
    op, pts = seg
    if op == "L":
        a, b = np.array(p0), np.array(pts[0])
        n = max(1, math.ceil(np.linalg.norm(b - a) / step))
        t = np.linspace(0, 1, n + 1)[1:, None]
        return a + (b - a) * t
    c = np.array([p0, *pts])
    n = max(2, math.ceil(sum(np.linalg.norm(c[1:] - c[:-1], axis=1)) / step))
    t = np.linspace(0, 1, n + 1)[1:, None]
    return ((1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1]
            + 3 * (1 - t) * t ** 2 * c[2] + t ** 3 * c[3])


def _dir(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _tangents(p0, seg):
    """The segment's direction where it leaves p0 and where it arrives."""
    op, pts = seg
    c = [np.array(p0)] + [np.array(p) for p in pts]
    out = next((q - c[0] for q in c[1:] if np.linalg.norm(q - c[0]) > 1e-9), c[-1] - c[0])
    into = next((c[-1] - q for q in reversed(c[:-1]) if np.linalg.norm(c[-1] - q) > 1e-9),
                c[-1] - c[0])
    return _dir(out), _dir(into)


def _bez(c, t):
    t = t[:, None]
    return ((1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1]
            + 3 * (1 - t) * t ** 2 * c[2] + t ** 3 * c[3])


def _fit(d, t1, t2, tol, out):
    """Fit points d (n × 2) from d[0] to d[-1], leaving along t1 and
    arriving against t2 (t2 points back into the curve), splitting where
    the fit strays most until every piece is within tol."""
    stack = [(d, t1, t2)]
    while stack:
        d, t1, t2 = stack.pop()
        n = len(d)
        if n == 2:
            dist = np.linalg.norm(d[1] - d[0]) / 3
            out.append((d[0] + t1 * dist, d[1] + t2 * dist, d[1]))
            continue
        chords = np.r_[0, np.cumsum(np.linalg.norm(d[1:] - d[:-1], axis=1))]
        u = chords / chords[-1] if chords[-1] > 0 else np.linspace(0, 1, n)
        for _ in range(8):
            c = _generate(d, u, t1, t2)
            err = np.sum((_bez(c, u) - d) ** 2, axis=1)
            k = int(np.argmax(err[1:-1])) + 1
            if err[k] <= tol * tol or err[k] > 16 * tol * tol:
                break
            u = _newton(c, d, u)
        if err[k] <= tol * tol:
            out.append((c[1], c[2], c[3]))
            continue
        tc = _dir(d[k - 1] - d[k + 1])
        stack.append((d[k:], -tc, t2))      # popped second
        stack.append((d[:k + 1], t1, tc))   # popped first, so the curves stay in order


def _generate(d, u, t1, t2):
    b0, b1, b2, b3 = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u ** 2, u ** 3
    a1, a2 = t1[None, :] * b1[:, None], t2[None, :] * b2[:, None]
    C = np.array([[np.sum(a1 * a1), np.sum(a1 * a2)], [np.sum(a1 * a2), np.sum(a2 * a2)]])
    tmp = d - (np.outer(b0 + b1, d[0]) + np.outer(b2 + b3, d[-1]))
    X = np.array([np.sum(a1 * tmp), np.sum(a2 * tmp)])
    det = C[0, 0] * C[1, 1] - C[0, 1] * C[1, 0]
    seg = np.linalg.norm(d[-1] - d[0])
    al = ar = seg / 3
    if abs(det) > 1e-12:
        l, r = (X[0] * C[1, 1] - X[1] * C[0, 1]) / det, (C[0, 0] * X[1] - C[1, 0] * X[0]) / det
        if l > 1e-6 * seg and r > 1e-6 * seg:
            al, ar = l, r
    return np.array([d[0], d[0] + t1 * al, d[-1] + t2 * ar, d[-1]])


def _newton(c, d, u):
    q = _bez(c, u)
    q1c, q2c = 3 * (c[1:] - c[:-1]), 6 * (c[2:] - 2 * c[1:-1] + c[:-2])
    t = u[:, None]
    q1 = (1 - t) ** 2 * q1c[0] + 2 * (1 - t) * t * q1c[1] + t ** 2 * q1c[2]
    q2 = (1 - t) * q2c[0] + t * q2c[1]
    num = np.sum((q - d) * q1, axis=1)
    den = np.sum(q1 * q1, axis=1) + np.sum((q - d) * q2, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        nu = np.where(np.abs(den) > 1e-12, u - num / den, u)
    nu = np.clip(nu, 0, 1)
    return nu if np.all(np.diff(nu) >= 0) else u


def simplify(path: Path, tolerance: float, step: float = 1.0) -> Path:
    out: Path = []
    for sub in path:
        start = np.array(sub[0][1][0])
        segs = sub[1:]
        if np.linalg.norm(np.array(segs[-1][1][-1]) - start) > 1e-6:
            segs = segs + [("L", (tuple(start),))]  # Z's closing line, made explicit
        # each segment's samples and its directions out of its start and into its end
        p, runs, outs, ins = start, [], [], []
        for seg in segs:
            o, i = _tangents(p, seg)
            outs.append(o)
            ins.append(i)
            runs.append(_sample(p, seg, step))
            p = seg[1][-1]
        corners = [i for i in range(len(segs))
                   if math.acos(max(-1.0, min(1.0, float(np.dot(ins[i - 1], outs[i]))))) > CORNER]
        pts = [start] + [q for r in runs for q in r]
        idx = np.cumsum([0] + [len(r) for r in runs])  # sample index where segment i starts
        d = np.array(pts)
        keep = np.r_[True, np.linalg.norm(d[1:] - d[:-1], axis=1) > 1e-9]
        breaks = sorted({int(np.sum(keep[:idx[i] + 1]) - 1) for i in corners})
        d = d[keep]
        if len(d) < 3:
            continue
        curves: list = []
        if not breaks:
            t = _dir(d[1] - d[-2])
            _fit(d, t, -t, tolerance, curves)
            first = d[0]
        else:
            # rotate so the contour begins at a corner, and fit corner to corner
            b0 = breaks[0]
            ring = np.r_[d[b0:-1], d[:b0 + 1]]
            bs = [b - b0 for b in breaks] + [len(ring) - 1]
            for a, b in zip(bs, bs[1:]):
                run = ring[a:b + 1]
                if len(run) < 2:
                    continue
                _fit(run, _dir(run[1] - run[0]), _dir(run[-2] - run[-1]), tolerance, curves)
            first = ring[0]
        out.append([("M", (tuple(first),))] + [("C", tuple(tuple(q) for q in c)) for c in curves])
    return out
