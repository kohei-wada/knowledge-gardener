#!/usr/bin/env python3
"""Phase 3 of issue #1 — Stop hook that silently writes today's session
block to the vault's daily note via headless Claude.

Opt-in: requires KG_AUTO_RECAP=1 in the environment. When unset (or any
other value), the hook is a fast no-op. See
docs/specs/2026-05-20-auto-recap-design.md for the design rationale.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import traceback

# Shared path helpers. auto_recap.py lives at skills/garden-recap/, so the
# repo-root lib/ is two parents up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "lib"))
from kg_paths import cursor_path as _shared_cursor_path  # noqa: E402
from kg_paths import debounce_marker as _shared_debounce_marker  # noqa: E402
from kg_paths import kg_state_dir, session_log_path as _shared_session_log_path  # noqa: E402

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


def plugin_root() -> pathlib.Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return pathlib.Path(env)
    # auto_recap.py lives at <plugin_root>/skills/garden-recap/auto_recap.py
    return pathlib.Path(__file__).resolve().parents[2]


def vault_root() -> pathlib.Path | None:
    v = os.environ.get("KG_VAULT")
    if not v:
        return None
    p = pathlib.Path(v)
    return p if p.is_dir() else None


SESSION_HEADER_RE = re.compile(r"^## Session (\d{2}:\d{2}) - (\d{2}:\d{2})", re.MULTILINE)
# Recap block heading: `## Session HH:MM 〜 <topic>` (full-width tilde 〜).
# We allow either form so prompt-template drift doesn't kill the topic.
BLOCK_HEADING_RE = re.compile(r"^##\s+Session\s+\d{2}:\d{2}\s*[〜~]\s*(.+?)\s*$", re.MULTILINE)


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


COMMIT_SUBJECT_LIMIT = 72


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


def read_text(path: pathlib.Path, limit: int = 20_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n…(truncated)\n"
    return text


def load_vault_context(vault: pathlib.Path) -> tuple[str, str]:
    """Return (readme_excerpt, daily_template_excerpt).

    The daily-note folder and filename are not pre-resolved here — they are
    discovered by Claude from the README inside the same prompt that composes
    the recap block (see parse_discovery / main).

    - KG_DAILY_TEMPLATE: optional env var. Relative to $KG_VAULT or absolute.
      When unset, the template excerpt is empty and the prompt instructs
      Claude to fall back to the README's description of the daily-note
      structure.
    """
    readme_parts: list[str] = []
    for candidate in (vault / "README.md", vault.parent / "README.md"):
        if candidate.is_file():
            readme_parts.append(f"--- {candidate} ---\n{read_text(candidate)}")
    readme_excerpt = "\n\n".join(readme_parts) or "(no README found)"

    template_path = _resolve_under_vault(vault, os.environ.get("KG_DAILY_TEMPLATE"))
    template_excerpt = (
        read_text(template_path) if template_path and template_path.is_file()
        else ""
    )

    return readme_excerpt, template_excerpt


def _resolve_under_vault(vault: pathlib.Path, raw: str | None) -> pathlib.Path | None:
    """Resolve a env-var path. Empty/None → None. Absolute → as-is. Relative → under vault."""
    if not raw:
        return None
    p = pathlib.Path(raw).expanduser()
    return p if p.is_absolute() else vault / p


def daily_note_path(daily_folder: pathlib.Path) -> pathlib.Path:
    return daily_folder / f"{_dt.date.today().isoformat()}.md"


def compose_prompt(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for k, v in substitutions.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def call_claude(prompt: str, timeout: int) -> str | None:
    cmd_name = os.environ.get("KG_AUTO_RECAP_CLAUDE_CMD", "claude")
    cmd_path = shutil.which(cmd_name) or cmd_name
    try:
        proc = subprocess.run(
            [cmd_path, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"claude invocation failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"claude exit={proc.returncode} stderr={proc.stderr[:300]!r}")
        return None
    return proc.stdout


# Marker format: <!-- kg-recap-sid:{sid8}-{HHMM} -->
# sid8 is the 8-char session prefix; HHMM is colon-stripped (e.g. 0957)
# because the regex character class below does not accept ':'.
MARKER_OPEN_RE = re.compile(r"<!--\s*kg-recap-sid:([A-Za-z0-9_-]+)\s*-->")
_DISCOVERY_BLOCK_RE = re.compile(
    r"<!--\s*kg-discovery\s*-->(.*?)<!--\s*/kg-discovery\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_DISCOVERY_LINE_RE = re.compile(r"^\s*(folder|filename|insert_before)\s*:\s*(.*?)\s*$", re.IGNORECASE)


def parse_discovery(claude_output: str) -> dict[str, str]:
    """Pull the kg-discovery block out of Claude's output as a dict.

    Returns {} on missing/malformed block. Keys present in the returned dict
    are exactly those Claude emitted with a non-empty value, lowercase.
    Supported keys: 'folder', 'filename', 'insert_before'.
    """
    m = _DISCOVERY_BLOCK_RE.search(claude_output)
    if not m:
        return {}
    out: dict[str, str] = {}
    for raw in m.group(1).splitlines():
        lm = _DISCOVERY_LINE_RE.match(raw)
        if not lm:
            continue
        key = lm.group(1).lower()
        val = lm.group(2).strip()
        if val:
            out[key] = val
    return out


def resolve_daily_path(vault: pathlib.Path, discovery: dict[str, str]) -> pathlib.Path | None:
    """Resolve today's daily-note path from env override or Claude discovery.

    Env precedence: KG_DAILY_FOLDER + KG_DAILY_FILENAME (if set) override
    Claude's discovery. When env is unset, discovery values are used. When
    neither yields a usable folder + filename, returns None (caller no-ops).
    """
    folder_raw = os.environ.get("KG_DAILY_FOLDER") or discovery.get("folder", "")
    filename = (os.environ.get("KG_DAILY_FILENAME") or discovery.get("filename") or "").strip()
    folder = _resolve_under_vault(vault, folder_raw)
    if folder is None or not filename:
        return None
    if not folder.is_dir():
        log(f"daily folder does not exist: {folder}")
        # Diagnostic hint: if the discovered folder begins with a path
        # component equal to the vault's own basename, the discovery step
        # most likely interpreted a directory-tree-style README literally and
        # prefixed the vault root onto `folder`. We do NOT auto-rewrite —
        # the README remains source of truth — but surface the likely cause
        # so the user can clarify their README or the discovery prompt.
        first = folder_raw.lstrip("/").split("/", 1)[0]
        if first and first == vault.name:
            log(
                f"hint: discovered folder {folder_raw!r} begins with the vault's "
                f"basename {vault.name!r}; discovery may have included a "
                f"directory-tree root node that already corresponds to $KG_VAULT"
            )
        return None
    if "/" in filename or filename.startswith("."):
        log(f"refusing suspicious daily filename: {filename!r}")
        return None
    return folder / filename


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


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        emit_continue()
        return

    if os.environ.get("KG_AUTO_RECAP") != "1":
        emit_continue()
        return

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        log("invalid hook payload")
        emit_continue()
        return

    if not isinstance(payload, dict):
        emit_continue()
        return

    session_id = payload.get("session_id") or ""
    sid8 = (session_id[:8] or "unknown")

    # debounce
    marker = debounce_marker(sid8)
    try:
        if marker.exists():
            age = time.time() - marker.stat().st_mtime
            if age < DEBOUNCE_SECONDS:
                emit_continue()
                return
    except OSError:
        pass

    vault = vault_root()
    if vault is None:
        log("KG_VAULT unset or invalid")
        emit_continue()
        return

    log_path = session_log_path(sid8)
    if not log_path.is_file() or log_path.stat().st_size == 0:
        emit_continue()
        return

    since = read_cursor(sid8)
    aggregator_output = run_aggregator(sid8, since=since)
    if not aggregator_output:
        emit_continue()
        return

    window = parse_session_window(aggregator_output)
    if window is None:
        log("could not parse Session header from aggregator output")
        emit_continue()
        return
    start_hhmm, end_hhmm = window
    marker_key = f"{sid8}-{start_hhmm.replace(':', '')}"

    readme, template = load_vault_context(vault)

    prompt_template_path = plugin_root() / "skills" / "garden-recap" / "auto_recap_prompt.md"
    if not prompt_template_path.is_file():
        log("prompt template missing")
        emit_continue()
        return
    prompt_template = prompt_template_path.read_text(encoding="utf-8")

    existing_daily = "(unknown until folder is discovered)"
    today_str = _dt.date.today().isoformat()
    prompt = compose_prompt(
        prompt_template,
        {
            "SID8": sid8,
            "MARKER_KEY": marker_key,
            "START_HHMM": start_hhmm,
            "TODAY": today_str,
            "VAULT_README": readme,
            "DAILY_TEMPLATE": template,
            "EXISTING_DAILY": existing_daily,
            "AGGREGATOR_OUTPUT": aggregator_output,
        },
    )

    timeout = int(os.environ.get("KG_AUTO_RECAP_TIMEOUT", str(DEFAULT_TIMEOUT)))
    out = call_claude(prompt, timeout=timeout)
    if not out:
        emit_continue()
        return

    discovery = parse_discovery(out)
    daily_path = resolve_daily_path(vault, discovery)
    if daily_path is None:
        log("could not resolve daily-note path (no env override and no discovery from README)")
        emit_continue()
        return

    block = extract_block(out, marker_key)
    if not block:
        log("claude output missing recap markers")
        emit_continue()
        return

    topic = extract_topic(block)
    if topic is None:
        log(f"could not extract topic from block for {marker_key}; using fallback subject")

    changed = upsert_block(daily_path, marker_key, block, insert_before=discovery.get("insert_before", ""))
    if not changed:
        emit_continue()
        return

    repo_root = find_repo_root(vault)
    if repo_root is None:
        log("vault is not in a git repo — skipping commit; cursor still updated")
        write_cursor(sid8, end_hhmm)
        emit_continue()
        return
    commit_and_push(repo_root, daily_path, marker_key, start_hhmm, topic)
    write_cursor(sid8, end_hhmm)

    try:
        marker = debounce_marker(sid8)
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.touch()
    except OSError:
        pass

    emit_continue()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("uncaught: " + traceback.format_exc().splitlines()[-1])
        emit_continue()
