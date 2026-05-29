#!/usr/bin/env python3
"""Phase 3 of issue #1 — Stop hook that silently writes today's session
block to the vault's daily note via headless Claude.

Opt-in: requires KG_AUTO_RECAP=1 in the environment. When unset (or any
other value), the hook is a fast no-op. See
docs/specs/2026-05-20-auto-recap-design.md for the design rationale.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import hashlib
import subprocess
import sys
import time
import traceback

# Shared path helpers. auto_recap.py lives at skills/garden-recap/, so the
# repo-root lib/ is two parents up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "lib"))
from kg_paths import cursor_path as _shared_cursor_path  # noqa: E402
from kg_paths import debounce_marker as _shared_debounce_marker  # noqa: E402
from kg_paths import discovery_cache_path as _shared_discovery_cache_path  # noqa: E402
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


# --- Discovery cache --------------------------------------------------------
#
# The vault README is the source of truth for daily-note folder/filename/etc.
# The auto-recap discovery step asks Claude to translate that README into
# concrete kg-discovery values on every Stop hook — but the README is stable
# across most sessions. We cache the discovery result keyed by a hash of the
# README content(s) so unchanged READMEs skip the discovery LLM work and the
# compose-only prompt can be used instead. README edits change the hash and
# naturally invalidate the cache; no TTL needed.

_CACHE_SCHEMA_VERSION = 1
_FILENAME_DATE_PLACEHOLDER = "{date}"


def _read_readme_bytes(vault: pathlib.Path) -> bytes:
    """Concatenate $KG_VAULT/README.md and $KG_VAULT/../README.md (if present)."""
    parts: list[bytes] = []
    for candidate in (vault / "README.md", vault.parent / "README.md"):
        try:
            parts.append(candidate.read_bytes())
        except OSError:
            continue
        parts.append(b"\x00")  # separator so two empty files don't collide with one
    return b"".join(parts)


def compute_readme_hash(vault: pathlib.Path) -> str | None:
    """SHA-256 of the vault's README content(s). None if no README is readable."""
    data = _read_readme_bytes(vault)
    if not data:
        return None
    return hashlib.sha256(data).hexdigest()


def discovery_cache_path(readme_hash: str) -> pathlib.Path:
    return _shared_discovery_cache_path(readme_hash)


def read_discovery_cache(readme_hash: str) -> dict[str, str] | None:
    """Return cached discovery values or None on miss / corruption.

    Only returns a dict when both `folder` and `filename_pattern` are present
    and non-empty (the minimum to skip the discovery LLM call). All other
    failure modes (missing file, JSON error, schema mismatch) return None so
    the caller falls back to the full discovery path.
    """
    path = discovery_cache_path(readme_hash)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log(f"discovery cache corrupted, ignoring: {path}")
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != _CACHE_SCHEMA_VERSION:
        return None
    if data.get("readme_hash") != readme_hash:
        return None
    folder = (data.get("folder") or "").strip()
    pattern = (data.get("filename_pattern") or "").strip()
    if not folder or not pattern:
        return None
    return {
        "folder": folder,
        "filename_pattern": pattern,
        "insert_before": (data.get("insert_before") or "").strip(),
    }


def write_discovery_cache(readme_hash: str, discovery: dict[str, str]) -> None:
    """Persist discovery values for future cache hits. Best-effort."""
    folder = (discovery.get("folder") or "").strip()
    pattern = (discovery.get("filename_pattern") or "").strip()
    if not folder or not pattern:
        return  # nothing useful to cache
    payload = {
        "schema": _CACHE_SCHEMA_VERSION,
        "readme_hash": readme_hash,
        "folder": folder,
        "filename_pattern": pattern,
        "insert_before": (discovery.get("insert_before") or "").strip(),
        "discovered_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    path = discovery_cache_path(readme_hash)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"discovery cache write failed: {e!r}")


def substitute_date(pattern: str, today_str: str) -> str:
    """Replace the literal {date} placeholder in a cached filename pattern."""
    if not pattern:
        return ""
    return pattern.replace(_FILENAME_DATE_PLACEHOLDER, today_str)


# --- end discovery cache ----------------------------------------------------


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


@dataclasses.dataclass(frozen=True)
class RecapContext:
    sid8: str
    vault: pathlib.Path
    today_str: str
    since: str | None

    @classmethod
    def from_hook(cls, raw_stdin: str, dict_env: dict[str, str]) -> "RecapContext | None":
        if dict_env.get("KG_AUTO_RECAP") != "1":
            return None
        try:
            payload = json.loads(raw_stdin) if raw_stdin else {}
        except Exception:
            log("invalid hook payload")
            return None
        if not isinstance(payload, dict):
            return None
        v = dict_env.get("KG_VAULT")
        if not v:
            log("KG_VAULT unset or invalid")
            return None
        vault = pathlib.Path(v)
        if not vault.is_dir():
            log("KG_VAULT unset or invalid")
            return None
        sid8 = (payload.get("session_id") or "")[:8] or "unknown"
        since = read_cursor(sid8)
        return cls(
            sid8=sid8,
            vault=vault,
            today_str=_dt.date.today().isoformat(),
            since=since,
        )


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
            [cmd_path, "-p"],
            input=prompt,
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
_DISCOVERY_LINE_RE = re.compile(
    r"^\s*(folder|filename|filename_pattern|insert_before)\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)


def parse_discovery(claude_output: str) -> dict[str, str]:
    """Pull the kg-discovery block out of Claude's output as a dict.

    Returns {} on missing/malformed block. Keys present in the returned dict
    are exactly those Claude emitted with a non-empty value, lowercase.
    Supported keys: 'folder', 'filename', 'filename_pattern', 'insert_before'.
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


def _validate_daily_path(
    vault: pathlib.Path, folder_raw: str, filename: str, *, context: str
) -> pathlib.Path | None:
    """Shared sanity checks for a resolved (folder, filename) pair.

    Logs the same diagnostic hint shape as the older inline version when a
    directory-tree-style README's vault-root node is mistakenly carried into
    the folder value. `context` distinguishes the call site in the log
    ("discovery" vs "pre-resolve") so the user can tell which path failed.
    """
    folder = _resolve_under_vault(vault, folder_raw)
    if folder is None or not filename:
        return None
    if not folder.is_dir():
        log(f"daily folder does not exist ({context}): {folder}")
        first = folder_raw.lstrip("/").split("/", 1)[0]
        if first and first == vault.name:
            log(
                f"hint: {context} folder {folder_raw!r} begins with the vault's "
                f"basename {vault.name!r}; discovery may have included a "
                f"directory-tree root node that already corresponds to $KG_VAULT"
            )
        return None
    if "/" in filename or filename.startswith("."):
        log(f"refusing suspicious daily filename ({context}): {filename!r}")
        return None
    return folder / filename


def resolve_daily_path(vault: pathlib.Path, discovery: dict[str, str]) -> pathlib.Path | None:
    """Resolve today's daily-note path from env override or Claude discovery.

    Env precedence: KG_DAILY_FOLDER + KG_DAILY_FILENAME (if set) override
    Claude's discovery. When env is unset, discovery values are used. When
    neither yields a usable folder + filename, returns None (caller no-ops).
    """
    folder_raw = os.environ.get("KG_DAILY_FOLDER") or discovery.get("folder", "")
    filename = (os.environ.get("KG_DAILY_FILENAME") or discovery.get("filename") or "").strip()
    return _validate_daily_path(vault, folder_raw, filename, context="discovery")


def pre_resolve_daily_path(
    vault: pathlib.Path,
    cached: dict[str, str] | None,
    today_str: str,
) -> tuple[pathlib.Path, str] | None:
    """Try to resolve today's daily-note path from env + discovery cache only.

    Returns (daily_path, insert_before) when both folder and filename can be
    determined without an LLM discovery call; returns None to signal the
    caller should fall back to the full discovery prompt.
    """
    env_folder = os.environ.get("KG_DAILY_FOLDER")
    env_filename = os.environ.get("KG_DAILY_FILENAME")
    env_insert = os.environ.get("KG_DAILY_INSERT_BEFORE")

    folder_raw = (env_folder or (cached.get("folder") if cached else "") or "").strip()
    if env_filename:
        filename = env_filename.strip()
    elif cached:
        filename = substitute_date(cached.get("filename_pattern", ""), today_str)
    else:
        filename = ""
    insert_before = (env_insert or (cached.get("insert_before") if cached else "") or "").strip()

    if not folder_raw or not filename:
        return None
    daily_path = _validate_daily_path(vault, folder_raw, filename, context="pre-resolve")
    if daily_path is None:
        return None
    return (daily_path, insert_before)


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
    today_str = _dt.date.today().isoformat()

    # Try to pre-resolve the daily path from env + cached discovery (no LLM call).
    # On a hit, we use the compose-only prompt which drops the README and the
    # discovery rules — a single, smaller prompt, still one LLM call.
    readme_hash = compute_readme_hash(vault)
    cached = read_discovery_cache(readme_hash) if readme_hash else None
    pre = pre_resolve_daily_path(vault, cached, today_str)

    if pre is not None:
        daily_path, insert_before = pre
        try:
            existing_daily = (
                daily_path.read_text(encoding="utf-8")
                if daily_path.is_file()
                else "(file does not exist yet)"
            )
        except OSError:
            existing_daily = "(file does not exist yet)"
        prompt_template_path = plugin_root() / "skills" / "garden-recap" / "auto_recap_compose_prompt.md"
    else:
        daily_path = None
        insert_before = ""
        existing_daily = "(unknown until folder is discovered)"
        prompt_template_path = plugin_root() / "skills" / "garden-recap" / "auto_recap_prompt.md"

    if not prompt_template_path.is_file():
        log(f"prompt template missing: {prompt_template_path}")
        emit_continue()
        return
    prompt_template = prompt_template_path.read_text(encoding="utf-8")

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

    discovery: dict[str, str] = {}
    if pre is None:
        discovery = parse_discovery(out)
        daily_path = resolve_daily_path(vault, discovery)
        if daily_path is None:
            log("could not resolve daily-note path (no env override and no discovery from README)")
            emit_continue()
            return
        insert_before = discovery.get("insert_before", "")

    block = extract_block(out, marker_key)
    if not block:
        log("claude output missing recap markers")
        emit_continue()
        return

    topic = extract_topic(block)
    if topic is None:
        log(f"could not extract topic from block for {marker_key}; using fallback subject")

    changed = upsert_block(daily_path, marker_key, block, insert_before=insert_before)
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

    # On a successful miss-path run, persist the discovered values so subsequent
    # Stop hooks (until the README changes) can skip the discovery LLM step.
    if pre is None and readme_hash and discovery.get("folder") and discovery.get("filename_pattern"):
        write_discovery_cache(readme_hash, discovery)

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
