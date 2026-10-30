"""Where the fonts are: out/fonts/, fetched by bin/fonts from the sources
and checksums fonts.json records, so every machine, CI included, cuts
from the same files the site uses."""

from pathlib import Path as File

ROOT = File(__file__).resolve().parent.parent
FONTS = ROOT / "out" / "fonts"
EBGI = str(FONTS / "EBGaramond-Initials.otf")
SPECTRAL = str(FONTS / "Spectral-{weight}.ttf")
