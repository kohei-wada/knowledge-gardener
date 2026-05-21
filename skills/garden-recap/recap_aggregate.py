#!/usr/bin/env python3
"""Phase 2 of issue #1 — aggregate session-capture logs into a recap-friendly summary.

See docs/specs/2026-05-20-recap-aggregator-design.md for the design rationale.
Plain stdlib only. Read-only: never writes back to the log dir.

Usage:
    skills/garden-recap/recap_aggregate.py [--date YYYY-MM-DD] [--sid SID8] [--all]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import sys
from collections import Counter, OrderedDict
from typing import Iterable

# Shared path helpers. recap_aggregate.py lives at skills/garden-recap/, so the
# repo-root lib/ is two parents up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "lib"))
from kg_paths import sessions_dir  # noqa: E402

LINE_RE = re.compile(
    r"^(?P<hhmm>\d{2}:\d{2})\s+"
    r"tool=(?P<tool>\S+)\s+"
    r"target=(?P<target>.*?)"
    r"(?:\s+\[status=(?P<status>ok|err)\])?\s*$"
)

FILE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
MAX_BASH_HIGHLIGHTS = 10


def list_logs_for_date(date: _dt.date) -> list[pathlib.Path]:
    d = sessions_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob(f"{date.isoformat()}-*.log"))


def parse_log(path: pathlib.Path) -> list[dict]:
    """Return list of parsed entries. Unparseable lines are silently dropped."""
    entries: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        entries.append(
            {
                "hhmm": m["hhmm"],
                "tool": m["tool"],
                "target": m["target"],
                "status": m["status"],  # may be None
            }
        )
    return entries


def session_id_from_path(path: pathlib.Path, date: _dt.date) -> str:
    """`<YYYY-MM-DD>-<sid8>.log` → `<sid8>`."""
    stem = path.stem
    prefix = f"{date.isoformat()}-"
    return stem[len(prefix):] if stem.startswith(prefix) else stem


SINCE_RE = re.compile(r"^\d{2}:\d{2}$")


def _validate_since(since: str | None) -> str | None:
    if since is None:
        return None
    if not SINCE_RE.match(since):
        raise ValueError(f"invalid --since: {since!r} (expected HH:MM)")
    return since


def aggregate_session(path: pathlib.Path, date: _dt.date, since: str | None = None) -> dict:
    entries = parse_log(path)
    if since is not None:
        entries = [e for e in entries if e["hhmm"] > since]
    sid8 = session_id_from_path(path, date)

    file_counts: OrderedDict[str, int] = OrderedDict()
    bash_seen: OrderedDict[str, None] = OrderedDict()
    agent_subagents: list[str] = []
    webio = 0
    mcp_servers: Counter[str] = Counter()
    errors = 0
    other = 0
    hhmms = [e["hhmm"] for e in entries]

    for e in entries:
        if e["status"] == "err":
            errors += 1
        tool = e["tool"]
        target = e["target"]

        if tool in FILE_TOOLS:
            file_counts[target] = file_counts.get(target, 0) + 1
        elif tool == "Bash":
            if target not in bash_seen and len(bash_seen) < MAX_BASH_HIGHLIGHTS:
                bash_seen[target] = None
        elif tool == "Agent":
            # target shape: <subagent>:<desc>
            sub = target.split(":", 1)[0] if ":" in target else target
            if sub and sub not in agent_subagents:
                agent_subagents.append(sub)
        elif tool in {"WebFetch", "WebSearch"}:
            webio += 1
        elif tool.startswith("mcp__"):
            parts = tool.split("__", 2)
            server = parts[1] if len(parts) >= 2 else "mcp"
            mcp_servers[server] += 1
        else:
            other += 1

    return {
        "sid8": sid8,
        "mtime": path.stat().st_mtime if path.exists() else 0,
        "entry_count": len(entries),
        "first_hhmm": hhmms[0] if hhmms else None,
        "last_hhmm": hhmms[-1] if hhmms else None,
        "duration_min": _duration_minutes(hhmms[0], hhmms[-1]) if hhmms else 0,
        "file_counts": file_counts,
        "bash_highlights": list(bash_seen.keys()),
        "agent_subagents": agent_subagents,
        "agent_count": sum(1 for e in entries if e["tool"] == "Agent"),
        "webio_count": webio,
        "mcp_servers": dict(mcp_servers),
        "errors": errors,
        "other_count": other,
    }


def _duration_minutes(start: str | None, end: str | None) -> int:
    if not start or not end:
        return 0

    def m(hhmm: str) -> int:
        h, mm = hhmm.split(":")
        return int(h) * 60 + int(mm)

    delta = m(end) - m(start)
    if delta < 0:
        delta += 24 * 60  # crossed midnight (Phase 1 should split, but be robust)
    return delta


def render_session(agg: dict) -> str:
    out: list[str] = []
    start = agg["first_hhmm"] or "--:--"
    end = agg["last_hhmm"] or "--:--"
    out.append(f"## Session {start} - {end} (sid8: {agg['sid8']})")
    out.append(f"Duration: {agg['duration_min']}m, {agg['entry_count']} captured tool calls.")
    out.append("")

    out.append("### Files touched")
    if agg["file_counts"]:
        for path, n in agg["file_counts"].items():
            label = f"({n} edits)" if n != 1 else "(1 edit)"
            out.append(f"- {path} {label}")
    else:
        out.append("- (none)")
    out.append("")

    out.append("### Bash highlights")
    if agg["bash_highlights"]:
        for cmd in agg["bash_highlights"]:
            out.append(f"- {cmd}")
    else:
        out.append("- (none)")
    out.append("")

    out.append("### Other tool activity")
    agent_line = f"Agent: {agg['agent_count']}"
    if agg["agent_subagents"]:
        agent_line += " dispatch(es) — " + ", ".join(agg["agent_subagents"])
    else:
        agent_line += " dispatch(es)"
    out.append(f"- {agent_line}")
    out.append(f"- WebFetch/WebSearch: {agg['webio_count']}")
    if agg["mcp_servers"]:
        parts = ", ".join(f"{s}({n})" for s, n in sorted(agg["mcp_servers"].items()))
        out.append(f"- MCP: {parts}")
    else:
        out.append("- MCP: 0")
    out.append(f"- Errors: {agg['errors']}")
    out.append("")
    return "\n".join(out)


def select_logs(logs: list[pathlib.Path], date: _dt.date, sid: str | None, all_flag: bool) -> list[pathlib.Path]:
    if not logs:
        return []
    if sid:
        suffix = f"-{sid}.log"
        return [p for p in logs if p.name.endswith(suffix)]
    if all_flag:
        return list(logs)
    # default: most recently modified
    return [max(logs, key=lambda p: p.stat().st_mtime)]


def render(date: _dt.date, sessions: Iterable[dict]) -> str:
    sessions = list(sessions)
    parts: list[str] = [f"# Sessions on {date.isoformat()}", f"{len(sessions)} session(s) found.", ""]
    for s in sessions:
        parts.append(render_session(s))
    return "\n".join(parts).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Aggregate knowledge-gardener session logs for garden-recap.")
    p.add_argument("--date", help="Date in YYYY-MM-DD format. Default: today (local time).")
    p.add_argument("--sid", help="Aggregate only the session with this sid8 prefix.")
    p.add_argument("--all", action="store_true", help="Include every session for the date instead of just the latest.")
    p.add_argument(
        "--since",
        help="Drop log entries with hhmm <= this value (strict greater-than). Format HH:MM.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.date:
        try:
            date = _dt.date.fromisoformat(args.date)
        except ValueError:
            sys.stderr.write(f"invalid --date: {args.date!r}\n")
            return 2
    else:
        date = _dt.date.today()

    try:
        since = _validate_since(args.since)
    except ValueError as e:
        sys.stderr.write(f"{e}\n")
        return 2

    logs = list_logs_for_date(date)
    selected = select_logs(logs, date, args.sid, args.all)
    aggregates = [aggregate_session(p, date, since=since) for p in selected]
    sys.stdout.write(render(date, aggregates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
