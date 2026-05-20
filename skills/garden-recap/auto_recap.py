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


def state_home() -> pathlib.Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(base)


def session_log_path(sid8: str, date: _dt.date | None = None) -> pathlib.Path:
    d = date or _dt.date.today()
    return state_home() / "knowledge-gardener" / "sessions" / f"{d.isoformat()}-{sid8}.log"


def debounce_marker(sid8: str) -> pathlib.Path:
    return state_home() / "knowledge-gardener" / "sessions" / f".last-recap-{sid8}"


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


def run_aggregator(sid8: str) -> str | None:
    script = plugin_root() / "skills" / "garden-recap" / "recap_aggregate.py"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--sid", sid8],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"aggregator failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"aggregator exit={proc.returncode} stderr={proc.stderr[:200]!r}")
        return None
    if "0 session(s) found" in proc.stdout:
        return None
    return proc.stdout


def read_text(path: pathlib.Path, limit: int = 20_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n…(truncated)\n"
    return text


def load_vault_context(vault: pathlib.Path) -> tuple[str, str, pathlib.Path | None]:
    """Return (readme_excerpt, daily_template_excerpt, daily_note_folder).

    Daily folder and template paths come from explicit env vars — no hardcoded
    folder names. Skills/garden-recap/SKILL.md and the README explain how to
    configure these.

    - KG_DAILY_FOLDER: required for auto-recap to write. Relative to $KG_VAULT
      (e.g. "04_DailyNotes") or absolute. If unset or the path doesn't exist,
      auto-recap degrades to no-op.
    - KG_DAILY_TEMPLATE: optional. Relative to $KG_VAULT or absolute. When
      unset, the template excerpt is "(no daily template configured)".
    """
    readme_parts: list[str] = []
    for candidate in (vault / "README.md", vault.parent / "README.md"):
        if candidate.is_file():
            readme_parts.append(f"--- {candidate} ---\n{read_text(candidate)}")
    readme_excerpt = "\n\n".join(readme_parts) or "(no README found)"

    daily_folder = _resolve_under_vault(vault, os.environ.get("KG_DAILY_FOLDER"))
    if daily_folder is not None and not daily_folder.is_dir():
        log(f"KG_DAILY_FOLDER does not exist: {daily_folder}")
        daily_folder = None

    template_path = _resolve_under_vault(vault, os.environ.get("KG_DAILY_TEMPLATE"))
    template_excerpt = (
        read_text(template_path) if template_path and template_path.is_file()
        else "(no daily template configured)"
    )

    return readme_excerpt, template_excerpt, daily_folder


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


MARKER_OPEN_RE = re.compile(r"<!--\s*kg-recap-sid:([A-Za-z0-9_-]+)\s*-->")


def extract_block(claude_output: str, sid8: str) -> str | None:
    open_re = re.compile(rf"<!--\s*kg-recap-sid:{re.escape(sid8)}\s*-->", re.IGNORECASE)
    close_re = re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(sid8)}\s*-->", re.IGNORECASE)
    om = open_re.search(claude_output)
    cm = close_re.search(claude_output)
    if not om or not cm or cm.start() <= om.start():
        return None
    return claude_output[om.start(): cm.end()]


def upsert_block(daily_path: pathlib.Path, sid8: str, block: str) -> bool:
    """Insert or replace the recap block in today's daily note. Returns True if file changed.

    Insertion anchor: when env var KG_DAILY_INSERT_BEFORE is set, treat its
    value as a literal heading and insert the new block immediately before it
    (with a leading newline). When unset, append at EOF.
    """
    existing = daily_path.read_text(encoding="utf-8") if daily_path.exists() else ""
    open_re = re.compile(rf"<!--\s*kg-recap-sid:{re.escape(sid8)}\s*-->", re.IGNORECASE)
    close_re = re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(sid8)}\s*-->", re.IGNORECASE)
    om = open_re.search(existing)
    cm = close_re.search(existing)
    if om and cm and cm.start() > om.start():
        new = existing[: om.start()] + block + existing[cm.end():]
    else:
        anchor = os.environ.get("KG_DAILY_INSERT_BEFORE", "").strip()
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


def commit_and_push(repo_root: pathlib.Path, daily_path: pathlib.Path, sid8: str) -> None:
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
    code, _, err = run_git(
        ["commit", "-m", f"water: {today} daily auto-recap (sid:{sid8})"],
        repo_root,
    )
    if code != 0:
        log(f"git commit failed: {err[:200]!r}")
        return
    if os.environ.get("KG_AUTO_RECAP_NO_PUSH") == "1":
        log(f"push skipped (KG_AUTO_RECAP_NO_PUSH=1) for {today} sid:{sid8}")
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

    aggregator_output = run_aggregator(sid8)
    if not aggregator_output:
        emit_continue()
        return

    readme, template, daily_folder = load_vault_context(vault)
    if daily_folder is None:
        log("no daily-note folder found")
        emit_continue()
        return

    daily_path = daily_note_path(daily_folder)
    existing_daily = read_text(daily_path) if daily_path.exists() else "(file does not exist yet)"

    prompt_template_path = plugin_root() / "skills" / "garden-recap" / "auto_recap_prompt.md"
    if not prompt_template_path.is_file():
        log("prompt template missing")
        emit_continue()
        return
    prompt_template = prompt_template_path.read_text(encoding="utf-8")

    start_hhmm = _dt.datetime.now().strftime("%H:%M")
    prompt = compose_prompt(
        prompt_template,
        {
            "SID8": sid8,
            "START_HHMM": start_hhmm,
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

    block = extract_block(out, sid8)
    if not block:
        log("claude output missing recap markers")
        emit_continue()
        return

    changed = upsert_block(daily_path, sid8, block)
    if not changed:
        emit_continue()
        return

    repo_root = find_repo_root(vault)
    if repo_root is None:
        log("vault is not in a git repo — skipping commit")
        emit_continue()
        return
    commit_and_push(repo_root, daily_path, sid8)

    # debounce update
    try:
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
