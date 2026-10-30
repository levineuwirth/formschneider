# Plain Python 3 scripts; `uv` supplies what the system lacks. potrace and
# rsvg-convert come from the system.
.PHONY: test calibrate scans
test:
	uv run --extra dev python -m pytest
calibrate:
	uv run bin/calibrate
scans:
	uv run bin/corpus fetch
	uv run bin/scans
