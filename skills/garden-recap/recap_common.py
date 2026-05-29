from __future__ import annotations

import datetime as _dt
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "lib"))
from kg_paths import cursor_path as _shared_cursor_path  # noqa: E402
from kg_paths import debounce_marker as _shared_debounce_marker  # noqa: E402
from kg_paths import discovery_cache_path as _shared_discovery_cache_path  # noqa: E402
from kg_paths import session_log_path as _shared_session_log_path  # noqa: E402

DEFAULT_TIMEOUT = 180
DEBOUNCE_SECONDS = 60
LOG_FILE = pathlib.Path.home() / ".local" / "state" / "knowledge-gardener" / "auto-recap.log"


def emit_continue() -> None:
    sys.stdout.write('{"continue": true, "suppressOutput": true}\n')
    sys.stdout.flush()


def log(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.now().isoformat(timespec="seconds")
            f.write(f"{ts} {line}\n")
    except OSError:
        pass


def session_log_path(sid8: str, date: _dt.date | None = None) -> pathlib.Path:
    return _shared_session_log_path(sid8, date)


def debounce_marker(sid8: str) -> pathlib.Path:
    return _shared_debounce_marker(sid8)


def cursor_path(sid8: str) -> pathlib.Path:
    return _shared_cursor_path(sid8)


def discovery_cache_path(readme_hash: str) -> pathlib.Path:
    return _shared_discovery_cache_path(readme_hash)


def plugin_root() -> pathlib.Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return pathlib.Path(env)
    # auto_recap.py lives at <plugin_root>/skills/garden-recap/auto_recap.py
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
