"""Keys from .env into the environment, without a dependency and without
ever printing them. A value already in the environment wins."""

import os
import re
from pathlib import Path as File

_LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)")


def parse(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        value = m.group(2).strip()
        if value[:1] in "'\"" and value[-1:] == value[:1] and len(value) > 1:
            value = value[1:-1]
        else:
            value = re.sub(r"(^|\s+)#.*$", "", value).strip()  # KEY=   # a note
        if value:
            out[m.group(1)] = value
    return out


def load(path: File) -> list[str]:
    """Set what the file holds; returns the names it set, never the values."""
    if not path.exists():
        return []
    found = parse(path.read_text())
    for k, v in found.items():
        os.environ.setdefault(k, v)
    return sorted(found)
