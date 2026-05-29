from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from recap_common import log, plugin_root  # noqa: E402
from recap_context import RecapContext  # noqa: E402

SESSION_HEADER_RE = re.compile(r"^## Session (\d{2}:\d{2}) - (\d{2}:\d{2})", re.MULTILINE)


def run_aggregator(sid8: str, since: str | None = None) -> str | None:
    script = plugin_root() / "skills" / "garden-recap" / "recap_aggregate.py"
    if not script.is_file():
        return None
    args = [sys.executable, str(script), "--sid", sid8]
    if since:
        args += ["--since", since]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"aggregator failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"aggregator exit={proc.returncode} stderr={proc.stderr[:200]!r}")
        return None
    if "0 session(s) found" in proc.stdout:
        return None
    # When --since filters out everything we still get 1 session block but
    # with `--:--` markers and 0 captured tool calls. Treat that as a no-op.
    if "Session --:-- - --:--" in proc.stdout or "0 captured tool calls" in proc.stdout:
        return None
    return proc.stdout


def parse_session_window(aggregator_output: str) -> tuple[str, str] | None:
    """Extract (start_hhmm, end_hhmm) from the aggregator's Session header."""
    m = SESSION_HEADER_RE.search(aggregator_output)
    if not m:
        return None
    return m.group(1), m.group(2)


@dataclasses.dataclass(frozen=True)
class Aggregation:
    text: str
    start_hhmm: str
    end_hhmm: str


class SessionAggregator:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def aggregate(self) -> Aggregation | None:
        out = run_aggregator(self._ctx.sid8, since=self._ctx.since)
        if not out:
            return None
        window = parse_session_window(out)
        if window is None:
            log("could not parse Session header from aggregator output")
            return None
        return Aggregation(text=out, start_hhmm=window[0], end_hhmm=window[1])
