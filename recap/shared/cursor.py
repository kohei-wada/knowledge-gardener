"""Per-session recap cursor I/O.

The cursor holds a single HH:MM line — the last log entry included in the most
recent successfully-written recap block. Split out of the former
recap/recap_common.py grab-bag.
"""
from __future__ import annotations

import re

from .hook_io import log
from .paths import cursor_path

SINCE_RE = re.compile(r"^\d{2}:\d{2}$")


def read_cursor(sid8: str) -> str | None:
    p = cursor_path(sid8)
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not SINCE_RE.match(text):
        log(f"ignoring malformed cursor at {p}: {text!r}")
        return None
    return text


def write_cursor(sid8: str, hhmm: str) -> None:
    p = cursor_path(sid8)
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_text(hhmm + "\n", encoding="utf-8")
    except OSError as e:
        log(f"cursor write failed: {e!r}")
