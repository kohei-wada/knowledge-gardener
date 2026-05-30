"""Shared pytest fixtures.

`recap.shared.hook_io.LOG_FILE` is computed at import time from `~/.local/state`.
Any in-process test that triggers `log()` (e.g. an error path in `daily_note`)
would otherwise append to the developer's REAL auto-recap log. Redirect it to a
per-test temp file so the suite never pollutes machine-local state. Subprocess
tests already isolate this via a fake `HOME` in their child env.
"""
from __future__ import annotations

import pytest

from recap.shared import hook_io


@pytest.fixture(autouse=True)
def _isolate_recap_log(tmp_path, monkeypatch):
    monkeypatch.setattr(hook_io, "LOG_FILE", tmp_path / "auto-recap.log")
