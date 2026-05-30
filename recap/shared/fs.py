"""Filesystem helpers: plugin root resolution, bounded text reads, vault-path resolution.

Split out of the former recap/recap_common.py grab-bag.
"""
from __future__ import annotations

import os
import pathlib


def plugin_root() -> pathlib.Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return pathlib.Path(env)
    # fs.py lives at <plugin_root>/recap/shared/fs.py
    return pathlib.Path(__file__).resolve().parents[2]


def read_text(path: pathlib.Path, limit: int = 20_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n…(truncated)\n"
    return text


def _resolve_under_vault(vault: pathlib.Path, raw: str | None) -> pathlib.Path | None:
    """Resolve a env-var path. Empty/None → None. Absolute → as-is. Relative → under vault."""
    if not raw:
        return None
    p = pathlib.Path(raw).expanduser()
    return p if p.is_absolute() else vault / p
