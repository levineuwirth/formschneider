"""On CI every test must run: a skip there means the runner lacks something
a test needs, and the workflow should say so rather than pass."""

import os


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    if os.environ.get("CI") and skipped:
        reporter.write_line(f"CI: {len(skipped)} skipped; every test must run here", red=True)
        session.exitstatus = 1
