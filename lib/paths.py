"""Path data as levineuwirth.org's initials write it: absolute, integer, M, L,
C and Z only, each pair joined by a comma: "M947,585C932,585 925,552 925,537Z".

A Path is a list of subpaths, each a list of (op, points) with op in "MLC";
every subpath is closed. `parse` also reads what potrace writes (relative
m, l, c), so traced and drawn outlines meet in one form.
"""

import re

Pt = tuple[float, float]
Seg = tuple[str, tuple[Pt, ...]]
Path = list[list[Seg]]

_TOKEN = re.compile(r"[MmLlCcZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARITY = {"M": 1, "L": 1, "C": 3}


def parse(d: str) -> Path:
    toks = _TOKEN.findall(d)
    path: Path = []
    sub: list[Seg] = []
    cur = start = (0.0, 0.0)
    op, i = "", 0
    while i < len(toks):
        if toks[i].isalpha():
            op, i = toks[i], i + 1
            if op in "Zz":
                if sub:
                    path.append(sub)
                sub, cur = [], start
                continue
        base = cur if op.islower() else (0.0, 0.0)
        pts = []
        for _ in range(_ARITY[op.upper()]):
            pts.append((base[0] + float(toks[i]), base[1] + float(toks[i + 1])))
            i += 2
        if op in "Mm":
            if sub:
                path.append(sub)
            sub, start = [("M", (pts[0],))], pts[0]
            op = "l" if op == "m" else "L"  # pairs after a moveto are linetos
        else:
            sub.append((op.upper(), tuple(pts)))
        cur = pts[-1]
    if sub:
        path.append(sub)
    return path


def transform(path: Path, f) -> Path:
    return [[(op, tuple(f(p) for p in pts)) for op, pts in sub] for sub in path]


def _n(v: float) -> str:
    return str(int(round(v)) or 0)


def fmt(path: Path) -> str:
    out = []
    for sub in path:
        for op, pts in sub:
            out.append(op + " ".join(f"{_n(x)},{_n(y)}" for x, y in pts))
        out.append("Z")
    return "".join(out)


def bounds(sub: list[Seg]) -> tuple[float, float, float, float]:
    xs = [x for _, pts in sub for x, _ in pts]
    ys = [y for _, pts in sub for _, y in pts]
    return min(xs), min(ys), max(xs), max(ys)
