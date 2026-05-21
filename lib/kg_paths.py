"""Shared path helpers for knowledge-gardener machine-local state.

Used by:
- skills/garden-recap/capture.py (PostToolUse hook — writes session log entries)
- skills/garden-recap/recap_aggregate.py (reads session logs)
- skills/garden-recap/auto_recap.py (reads session log, writes debounce marker)

All three previously duplicated the XDG_STATE_HOME resolution and the
"<state>/knowledge-gardener/sessions/" path construction. Centralized here
so future changes (e.g. moving sessions/ to data/ per XDG, or adding
encryption) happen in one place.

Plain stdlib only (no third-party deps), since `capture.py` runs inside a
synchronous PostToolUse hook and `auto_recap.py` runs inside a Stop hook
— neither can afford an import-time pip dependency.
"""
from __future__ import annotations

import datetime as _dt
import os
import pathlib


def state_home() -> pathlib.Path:
    """Resolve $XDG_STATE_HOME with the standard ~/.local/state fallback."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(base)


def kg_state_dir() -> pathlib.Path:
    """Root of knowledge-gardener's machine-local state tree."""
    return state_home() / "knowledge-gardener"


def sessions_dir() -> pathlib.Path:
    """Where per-session capture logs live."""
    return kg_state_dir() / "sessions"


def session_log_path(sid8: str, date: _dt.date | None = None) -> pathlib.Path:
    """Path to one session's capture log: `<sessions>/<YYYY-MM-DD>-<sid8>.log`."""
    d = (date or _dt.date.today()).isoformat()
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f"{d}-{safe_sid}.log"


def debounce_marker(sid8: str) -> pathlib.Path:
    """Path to the per-session auto-recap debounce marker."""
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f".last-recap-{safe_sid}"


def cursor_path(sid8: str) -> pathlib.Path:
    """Path to the per-session recap cursor file.

    Holds a single HH:MM line — the last log entry included in the most
    recent successfully-written block. Read by auto_recap.py to scope the
    next aggregation window via --since.
    """
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f"{safe_sid}.cursor"


def discovery_cache_dir() -> pathlib.Path:
    """Where auto-recap caches per-vault README-driven discovery results."""
    return kg_state_dir() / "discovery"


def discovery_cache_path(readme_hash: str) -> pathlib.Path:
    """Path to one vault's cached discovery, keyed by README content hash.

    The hash uniquely identifies a README revision; when the README changes
    the hash changes, naturally invalidating the cache without any TTL.
    """
    safe = "".join(c for c in readme_hash if c.isalnum())[:64] or "unknown"
    return discovery_cache_dir() / f"{safe}.json"
