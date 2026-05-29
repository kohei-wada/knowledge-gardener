from __future__ import annotations

import datetime as _dt
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from recap_common import log  # noqa: E402

COMMIT_SUBJECT_LIMIT = 72


def build_commit_subject(today: str, start_hhmm: str, topic: str | None, marker_key: str) -> str:
    """Compose the auto-recap commit subject line.

    With a topic: `water: {today} {HH:MM} 〜 {topic}`, truncated to 72 chars
    with an ellipsis if needed.
    Without a topic: keep the legacy `water: {today} daily auto-recap ({marker_key})` form.
    """
    if topic is None:
        return f"water: {today} daily auto-recap ({marker_key})"
    subject = f"water: {today} {start_hhmm} 〜 {topic}"
    if len(subject) > COMMIT_SUBJECT_LIMIT:
        subject = subject[: COMMIT_SUBJECT_LIMIT - 1] + "…"
    return subject


# Recap block heading: `## Session HH:MM 〜 <topic>` (full-width tilde 〜).
# We allow either form so prompt-template drift doesn't kill the topic.
BLOCK_HEADING_RE = re.compile(r"^##\s+Session\s+\d{2}:\d{2}\s*[〜~]\s*(.+?)\s*$", re.MULTILINE)


def extract_topic(block: str) -> str | None:
    """Pull `<topic>` from the block's `## Session HH:MM 〜 <topic>` heading.

    Returns None if the heading is missing or the topic is empty — callers
    fall back to the marker-key-only commit subject so a prompt-format drift
    doesn't break the commit pipeline.
    """
    m = BLOCK_HEADING_RE.search(block)
    if not m:
        return None
    topic = m.group(1).strip()
    return topic or None


def extract_block(claude_output: str, marker_key: str) -> str | None:
    open_re = re.compile(rf"<!--\s*kg-recap-sid:{re.escape(marker_key)}\s*-->", re.IGNORECASE)
    close_re = re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(marker_key)}\s*-->", re.IGNORECASE)
    om = open_re.search(claude_output)
    cm = close_re.search(claude_output)
    if not om or not cm or cm.start() <= om.start():
        return None
    return claude_output[om.start(): cm.end()]


def upsert_block(
    daily_path: pathlib.Path, marker_key: str, block: str, insert_before: str = ""
) -> bool:
    """Insert or replace the recap block in today's daily note. Returns True if file changed.

    Idempotency: a block with the EXACT same marker_key (sid8-HHMM) is
    replaced in place — needed for retry after pre-commit failure. Blocks
    keyed by any other marker_key are left untouched, so prior Stop events'
    blocks accumulate chronologically.

    Insertion anchor: when `insert_before` (or env var KG_DAILY_INSERT_BEFORE
    as override) is non-empty, treat its value as a literal heading and insert
    the new block immediately before it (with a leading newline). When both
    are empty, append at EOF.
    """
    existing = daily_path.read_text(encoding="utf-8") if daily_path.exists() else ""
    open_re = re.compile(rf"<!--\s*kg-recap-sid:{re.escape(marker_key)}\s*-->", re.IGNORECASE)
    close_re = re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(marker_key)}\s*-->", re.IGNORECASE)
    om = open_re.search(existing)
    cm = close_re.search(existing)
    if om and cm and cm.start() > om.start():
        new = existing[: om.start()] + block + existing[cm.end():]
    else:
        anchor = (os.environ.get("KG_DAILY_INSERT_BEFORE") or insert_before or "").strip()
        m = re.search(r"\n" + re.escape(anchor), existing) if anchor else None
        if m:
            new = existing[: m.start()] + "\n" + block + "\n" + existing[m.start():]
        else:
            sep = "" if existing.endswith("\n") or not existing else "\n"
            new = existing + sep + block + "\n"
    if new == existing:
        return False
    try:
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        daily_path.write_text(new, encoding="utf-8")
    except OSError as e:
        log(f"daily write failed: {e!r}")
        return False
    return True


def run_git(args: list[str], cwd: pathlib.Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


def commit_and_push(
    repo_root: pathlib.Path,
    daily_path: pathlib.Path,
    marker_key: str,
    start_hhmm: str,
    topic: str | None,
) -> None:
    rel = daily_path.relative_to(repo_root) if str(daily_path).startswith(str(repo_root)) else daily_path
    # pre-commit (best-effort)
    if (repo_root / ".pre-commit-config.yaml").is_file():
        try:
            subprocess.run(
                ["pre-commit", "run", "--files", str(rel)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"pre-commit failed: {e!r}")
    code, _, err = run_git(["add", str(rel)], repo_root)
    if code != 0:
        log(f"git add failed: {err[:200]!r}")
        return
    today = _dt.date.today().isoformat()
    subject = build_commit_subject(today, start_hhmm, topic, marker_key)
    code, _, err = run_git(
        ["commit", "-m", subject],
        repo_root,
    )
    if code != 0:
        log(f"git commit failed: {err[:200]!r}")
        return
    if os.environ.get("KG_AUTO_RECAP_NO_PUSH") == "1":
        log(f"push skipped (KG_AUTO_RECAP_NO_PUSH=1) for {today} {marker_key}")
        return
    code, _, err = run_git(["push"], repo_root)
    if code != 0:
        log(f"git push failed: {err[:200]!r}")


def find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand
    return None


class DailyNote:
    def __init__(self, vault: pathlib.Path, daily_path: pathlib.Path) -> None:
        self._daily_path = daily_path
        self._repo_root = find_repo_root(vault)

    @property
    def has_repo(self) -> bool:
        return self._repo_root is not None

    def apply_block(self, marker_key: str, block: str, insert_before: str) -> bool:
        return upsert_block(self._daily_path, marker_key, block, insert_before=insert_before)

    def commit(self, marker_key: str, start_hhmm: str, topic: str | None) -> None:
        if self._repo_root is None:
            return
        commit_and_push(self._repo_root, self._daily_path, marker_key, start_hhmm, topic)
