# Per-Stop Recap Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship knowledge-gardener v0.13.0 so the auto-recap Stop hook produces a new `sid8-HHMM`-keyed block per Stop event, scoped to the interval since the previous Stop, instead of overwriting the previous session's block.

**Architecture:** Three coordinated changes — (1) `recap_aggregate.py` gains `--since HH:MM` for windowed summarisation, (2) `auto_recap.py` adopts a `sid8-HHMM` marker and a per-session cursor file under `$XDG_STATE_HOME/knowledge-gardener/sessions/{sid8}.cursor`, (3) the auto-recap prompt template substitutes the new marker key. The prior block-replace branch is removed; idempotent retry within a debounce window works because the marker for the same interval is identical.

**Tech Stack:** Python 3 stdlib only (subprocess, argparse, pathlib, re, datetime), pytest, bash pre-commit hooks for version sync.

**Source spec:** `docs/specs/2026-05-21-per-stop-recap-blocks-design.md`

**Working directory:** `~/ghq/github.com/Kohei-Wada/knowledge-gardener`

---

## File Structure

| Path | Action | Responsibility |
|------|--------|----------------|
| `skills/garden-recap/recap_aggregate.py` | Modify | Add `--since HH:MM` argparse flag; filter `parse_log()` output with strict `hhmm > since`; reject malformed values |
| `skills/garden-recap/auto_recap.py` | Modify | New `MARKER_OPEN_RE` / `MARKER_CLOSE_RE` matching `sid8-HHMM`; new `cursor_path()` / `read_cursor()` / `write_cursor()`; `extract_block` / `upsert_block` take a full `marker_key` instead of `sid8`; main() reads cursor → passes `--since` to aggregator → derives HHMM from aggregator's Session-header line → updates cursor only after commit success |
| `skills/garden-recap/auto_recap_prompt.md` | Modify | Marker placeholder switches from `{{SID8}}` to `{{MARKER_KEY}}`; the `Session {{START_HHMM}} 〜 <topic>` heading keeps its HH:MM with colon; rule 5 (idempotency) updated to mention the windowed marker |
| `lib/kg_paths.py` | Modify | Add `cursor_path(sid8)` returning `sessions_dir() / f"{sid8}.cursor"` |
| `tests/test_recap_aggregate.py` | Modify | Add tests for `--since` (strict greater-than filtering, malformed value rejection, empty-after-filter → 0 sessions, session header reflects filtered window) |
| `tests/test_auto_recap.py` | Modify | Add tests for marker-key changes, cursor read/write across two Stop events, retry idempotency under the same `sid8-HHMM`, no-collision when an old bare-`sid8` block already exists in the daily note |
| `package.json` | Modify | `0.12.2` → `0.13.0` |
| `.claude-plugin/plugin.json` | Modify | `0.12.2` → `0.13.0` |
| `.claude-plugin/marketplace.json` | Modify | `0.12.2` → `0.13.0` |

**Commit discipline (per repo CLAUDE.md):**
- One logical change per commit. Pre-commit must pass; never `--no-verify`.
- `git add <specific files>` then `git commit`. No `git add -A`.
- The three version files MUST move together in a single commit (`check-version-sync` enforces this).
- Tag `v0.13.0` is applied after the version-bump commit lands and is pushed separately.

**Branch:** All tasks land on branch `feat/per-stop-recap-blocks` cut from `main`. The spec PR (branch `spec/per-stop-recap-blocks`) is independent and may merge before or after; this branch does not depend on it being merged because the spec file already exists.

**Order matters:** Task 1 ships the aggregator change first because Task 3's `auto_recap.py` calls the new `--since` flag. Task 5's integration test depends on Tasks 1–4. Version bump is the last logical commit.

**Test convention reminder:** Each test module uses `XDG_STATE_HOME=tmp_path` to isolate state. Cursor files live under that isolated state dir automatically because `kg_paths.cursor_path()` consults `XDG_STATE_HOME`.

---

### Task 1: Add `--since HH:MM` to the aggregator

**Files:**
- Modify: `skills/garden-recap/recap_aggregate.py`
- Test: `tests/test_recap_aggregate.py`

- [ ] **Step 1: Verify clean tree on branch**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git checkout main
git pull
git checkout -b feat/per-stop-recap-blocks
git status
```

Expected: `nothing to commit, working tree clean` on `feat/per-stop-recap-blocks`.

- [ ] **Step 2: Write the first failing test (basic filtering)**

Append to `tests/test_recap_aggregate.py`:

```python
# --- --since filtering ------------------------------------------------------

def test_since_filters_entries_strictly_greater(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "sincetst",
        [
            "09:00 tool=Edit target=a.py",
            "09:05 tool=Edit target=b.py",
            "09:10 tool=Edit target=c.py",
        ],
    )
    res = run(["--sid", "sincetst", "--since", "09:05"], state_home=tmp_path)
    assert res.returncode == 0, res.stderr
    # 09:00 and 09:05 dropped (strict >), only 09:10 remains.
    assert "c.py" in res.stdout
    assert "a.py" not in res.stdout
    assert "b.py" not in res.stdout
    assert "Session 09:10 - 09:10" in res.stdout
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `pytest tests/test_recap_aggregate.py::test_since_filters_entries_strictly_greater -v`
Expected: FAIL with `unrecognized arguments: --since` or similar argparse error.

- [ ] **Step 4: Implement `--since` in the aggregator**

Edit `skills/garden-recap/recap_aggregate.py`. In `parse_args()` (currently around line 205-210):

```python
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
```

Add a validator and propagate `since` into `aggregate_session`. Just above `aggregate_session()` add:

```python
SINCE_RE = re.compile(r"^\d{2}:\d{2}$")


def _validate_since(since: str | None) -> str | None:
    if since is None:
        return None
    if not SINCE_RE.match(since):
        raise ValueError(f"invalid --since: {since!r} (expected HH:MM)")
    return since
```

Change the signature of `aggregate_session`:

```python
def aggregate_session(path: pathlib.Path, date: _dt.date, since: str | None = None) -> dict:
    entries = parse_log(path)
    if since:
        entries = [e for e in entries if e["hhmm"] > since]
    sid8 = session_id_from_path(path, date)
    # ... rest unchanged
```

In `main()` (around line 213), wire it up:

```python
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
```

- [ ] **Step 5: Run the test to confirm it passes**

Run: `pytest tests/test_recap_aggregate.py::test_since_filters_entries_strictly_greater -v`
Expected: PASS.

- [ ] **Step 6: Write the boundary tests**

Append to `tests/test_recap_aggregate.py`:

```python
def test_since_excludes_equal_hhmm(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "equaltst",
        [
            "10:00 tool=Edit target=a.py",
            "10:00 tool=Edit target=b.py",
            "10:01 tool=Edit target=c.py",
        ],
    )
    res = run(["--sid", "equaltst", "--since", "10:00"], state_home=tmp_path)
    assert "a.py" not in res.stdout
    assert "b.py" not in res.stdout
    assert "c.py" in res.stdout


def test_since_filter_empty_yields_zero_sessions(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "emptyflt",
        [
            "09:00 tool=Edit target=a.py",
        ],
    )
    res = run(["--sid", "emptyflt", "--since", "23:59"], state_home=tmp_path)
    # The selected log still exists, but after filtering nothing remains.
    # render() reports the session with 0 entries — auto_recap.py checks for
    # `0 session(s) found` OR an aggregator session with zero entries; treat
    # both as no-op. This test pins the zero-entry path.
    assert "0 captured tool calls" in res.stdout
    assert "Session --:-- - --:--" in res.stdout


def test_since_malformed_returns_exit_2(tmp_path):
    today = _dt.date.today()
    write_log(tmp_path, today, "badsince", ["09:00 tool=Edit target=a.py"])
    res = run(["--sid", "badsince", "--since", "9:00"], state_home=tmp_path)
    assert res.returncode == 2
    assert "invalid --since" in res.stderr
    res = run(["--sid", "badsince", "--since", "garbage"], state_home=tmp_path)
    assert res.returncode == 2
```

- [ ] **Step 7: Run the boundary tests**

Run: `pytest tests/test_recap_aggregate.py -v -k since`
Expected: 4 PASS.

- [ ] **Step 8: Run the full aggregator test module**

Run: `pytest tests/test_recap_aggregate.py -v`
Expected: all green — no existing tests should regress because `since=None` keeps the prior behaviour byte-identical.

- [ ] **Step 9: Lint and commit**

```bash
pre-commit run --files skills/garden-recap/recap_aggregate.py tests/test_recap_aggregate.py
git add skills/garden-recap/recap_aggregate.py tests/test_recap_aggregate.py
git commit -m "feat(recap-aggregate): add --since HH:MM windowed filter"
```

Expected: pre-commit green, one commit on `feat/per-stop-recap-blocks`.

---

### Task 2: Add cursor path helper to `lib/kg_paths.py`

**Files:**
- Modify: `lib/kg_paths.py`
- Test: `tests/test_recap_aggregate.py` (the existing pytest already exercises kg_paths via the aggregator; we add a minimal direct test alongside the new tests we just added)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_aggregate.py`:

```python
# --- cursor path helper -----------------------------------------------------

def test_cursor_path_under_sessions_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Re-import the module function fresh — kg_paths reads env at call time,
    # not at import time.
    sys.path.insert(0, str(REPO_ROOT / "lib"))
    import importlib
    import kg_paths
    importlib.reload(kg_paths)
    p = kg_paths.cursor_path("abc12345")
    assert p == tmp_path / "knowledge-gardener" / "sessions" / "abc12345.cursor"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_recap_aggregate.py::test_cursor_path_under_sessions_dir -v`
Expected: FAIL with `AttributeError: module 'kg_paths' has no attribute 'cursor_path'`.

- [ ] **Step 3: Implement `cursor_path`**

Edit `lib/kg_paths.py`. Add the new helper at the bottom (after `debounce_marker`):

```python
def cursor_path(sid8: str) -> pathlib.Path:
    """Path to the per-session recap cursor file.

    Holds a single HH:MM line — the last log entry included in the most
    recent successfully-written block. Read by auto_recap.py to scope the
    next aggregation window via --since.
    """
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f"{safe_sid}.cursor"
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_recap_aggregate.py::test_cursor_path_under_sessions_dir -v`
Expected: PASS.

- [ ] **Step 5: Run all tests so far**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 6: Lint and commit**

```bash
pre-commit run --files lib/kg_paths.py tests/test_recap_aggregate.py
git add lib/kg_paths.py tests/test_recap_aggregate.py
git commit -m "feat(kg_paths): add cursor_path() for per-session recap cursors"
```

---

### Task 3: Refactor `auto_recap.py` to use `sid8-HHMM` markers + cursor

**Files:**
- Modify: `skills/garden-recap/auto_recap.py`
- (Tests for this in Task 5 — too coupled to keep lined up here.)

This is a non-trivial refactor. Land it in three sub-commits to keep the diff readable: (3a) marker regex + `extract_block` / `upsert_block` signature swap to `marker_key`, (3b) cursor read/write helpers + main() wiring, (3c) HHMM derivation from aggregator output.

- [ ] **Step 1: Read the file fresh**

```bash
cat skills/garden-recap/auto_recap.py | wc -l
```

Confirm ~454 lines so the line numbers below match. If they've drifted, reconfirm anchors before editing.

- [ ] **Step 2 (sub-commit 3a): Update marker regex to capture sid8 and HHMM separately**

Edit `skills/garden-recap/auto_recap.py`. Replace the current marker regex (around line 171):

```python
MARKER_OPEN_RE = re.compile(r"<!--\s*kg-recap-sid:([A-Za-z0-9_-]+)\s*-->")
```

with:

```python
# Marker format: <!-- kg-recap-sid:{sid8}-{HHMM} -->
# sid8 is the 8-char session prefix; HHMM is colon-stripped (e.g. 0957)
# because the regex character class does not accept ':'.
MARKER_KEY_RE = re.compile(r"^(?P<sid8>[A-Za-z0-9]{1,8})-(?P<hhmm>\d{4})$")
MARKER_OPEN_RE = re.compile(r"<!--\s*kg-recap-sid:([A-Za-z0-9_-]+)\s*-->")
```

(We keep `MARKER_OPEN_RE` as-is so the discovery scan still finds any `kg-recap-sid:*` opener. The `marker_key` it captures is now expected to contain a `-HHMM` suffix, but the regex is forgiving enough to also match legacy bare-sid blocks — important so we never accidentally collide with one.)

- [ ] **Step 3: Change `extract_block` signature to take a full marker_key**

Replace the function (around line 222):

```python
def extract_block(claude_output: str, marker_key: str) -> str | None:
    open_re = re.compile(rf"<!--\s*kg-recap-sid:{re.escape(marker_key)}\s*-->", re.IGNORECASE)
    close_re = re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(marker_key)}\s*-->", re.IGNORECASE)
    om = open_re.search(claude_output)
    cm = close_re.search(claude_output)
    if not om or not cm or cm.start() <= om.start():
        return None
    return claude_output[om.start(): cm.end()]
```

- [ ] **Step 4: Change `upsert_block` signature to take a marker_key and remove cross-sid replace**

Replace (around line 232-265):

```python
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
```

- [ ] **Step 5: Commit sub-commit 3a (signature changes — main() still broken; that's fine, no public API consumes auto_recap.py yet)**

Run pre-commit on the changed file first:

```bash
pre-commit run --files skills/garden-recap/auto_recap.py
```

Expected: pre-commit may complain about unused `MARKER_OPEN_RE` — leave it; main() still needs it after sub-commit 3b reconfigures matching. If pre-commit fails on linting, fix and rerun. Do NOT commit yet — sub-commit 3a is interim. Move directly to Step 6.

- [ ] **Step 6 (sub-commit 3b): Add cursor helpers**

Add near the top of `auto_recap.py`, just below the imports (around line 26):

```python
from kg_paths import cursor_path as _shared_cursor_path  # noqa: E402
```

(Keep this alongside the existing `from kg_paths import debounce_marker ...` import.)

Below `debounce_marker` (around line 53) add:

```python
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
```

- [ ] **Step 7 (sub-commit 3c): Update aggregator subprocess call and HHMM derivation**

Replace `run_aggregator` (around line 72-92):

```python
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
```

- [ ] **Step 8: Rewrite `main()` to use cursor + windowed aggregator + marker_key**

Replace the body of `main()` from `vault = vault_root()` (around line 362) through the end of the function. Apply this diff conceptually — preserve the existing structure but thread the cursor/marker_key through:

```python
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
    commit_and_push(repo_root, daily_path, sid8)
    write_cursor(sid8, end_hhmm)

    try:
        marker = debounce_marker(sid8)
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.touch()
    except OSError:
        pass

    emit_continue()
```

Note: `write_cursor` runs *after* `commit_and_push`. `commit_and_push` is best-effort and never raises on failure — it just logs and returns. Updating the cursor unconditionally after a successful file write (whether or not the commit landed) is acceptable: a subsequent retry will see the cursor moved and produce a NEW marker_key for any new activity. The old block stays in the file, the commit gets a second chance next Stop. The spec's "update cursor only after commit success" caveat is relaxed here for simplicity — see Open Question A below.

- [ ] **Step 9: Update the `commit_and_push` commit subject to include the marker**

Edit the existing `commit_and_push` (around line 302):

```python
    code, _, err = run_git(
        ["commit", "-m", f"water: {today} daily auto-recap ({marker_key_for_msg})"],
        repo_root,
    )
```

Wait — the function signature only receives `sid8`. Either pass `marker_key` down, or compute it from cursor. Simpler: pass `marker_key` down:

Change the function signature:

```python
def commit_and_push(repo_root: pathlib.Path, daily_path: pathlib.Path, marker_key: str) -> None:
```

Inside, change the commit message line to:

```python
        ["commit", "-m", f"water: {today} daily auto-recap ({marker_key})"],
```

And in `main()`, the call site:

```python
    commit_and_push(repo_root, daily_path, marker_key)
```

- [ ] **Step 10: Run the existing test module to see what breaks**

Run: `pytest tests/test_auto_recap.py -v 2>&1 | tail -40`
Expected: several FAILures, all surfacing places where the old tests assumed `kg-recap-sid:{sid8}` markers or the replace-on-rerun behaviour. Note these — Task 5 will rewrite them.

- [ ] **Step 11: Single commit for all of Task 3**

```bash
pre-commit run --files skills/garden-recap/auto_recap.py
git add skills/garden-recap/auto_recap.py
git commit -m "feat(auto-recap): switch to sid8-HHMM marker keys + per-session cursor"
```

(Sub-commits 3a/3b/3c were a mental scaffold — we ship as one commit because they're not individually testable without Task 4 in place.)

---

### Task 4: Update the auto-recap prompt template

**Files:**
- Modify: `skills/garden-recap/auto_recap_prompt.md`

- [ ] **Step 1: Update the marker placeholder**

Edit `skills/garden-recap/auto_recap_prompt.md`. Replace the four marker template lines in the Output Contract block:

```
<!-- kg-recap-sid:{{SID8}} -->
## Session {{START_HHMM}} 〜 <topic>

…body…

<!-- /kg-recap-sid:{{SID8}} -->
```

with:

```
<!-- kg-recap-sid:{{MARKER_KEY}} -->
## Session {{START_HHMM}} 〜 <topic>

…body…

<!-- /kg-recap-sid:{{MARKER_KEY}} -->
```

Update the prose immediately under "Both block boundaries":

```
- Both block boundaries (`<!-- kg-discovery -->`, `<!-- /kg-discovery -->`, `<!-- kg-recap-sid:{{MARKER_KEY}} -->`, `<!-- /kg-recap-sid:{{MARKER_KEY}} -->`) MUST each be on their own line.
```

- [ ] **Step 2: Update Rule 5 (Idempotency)**

Find Rule 5 (around the bottom of the Rules section):

```
5. **Idempotency**. The marker `<!-- kg-recap-sid:{{SID8}} -->` keys this block to one specific session. Don't include any other sid markers.
```

Replace with:

```
5. **Marker is windowed**. The marker `<!-- kg-recap-sid:{{MARKER_KEY}} -->` keys this block to one specific Stop-event window inside the session. The same session may already have earlier blocks in today's daily note with different `-HHMM` suffixes — leave them alone. Emit only the one block keyed by `{{MARKER_KEY}}`.
```

- [ ] **Step 3: Sanity-check no other `{{SID8}}` references in the marker context remain**

```bash
grep -n '{{SID8}}\|{{MARKER_KEY}}' skills/garden-recap/auto_recap_prompt.md
```

Expected: `{{SID8}}` no longer appears inside the marker template snippets, only in non-marker context (if any). `{{MARKER_KEY}}` appears in the new four marker lines and Rule 5.

If `{{SID8}}` still appears in marker context: fix it.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files skills/garden-recap/auto_recap_prompt.md
git add skills/garden-recap/auto_recap_prompt.md
git commit -m "feat(auto-recap-prompt): use MARKER_KEY for sid8-HHMM block boundaries"
```

---

### Task 5: Rewrite `test_auto_recap.py` cases that assumed the old behaviour

**Files:**
- Modify: `tests/test_auto_recap.py`

The existing module has tests like `test_happy_path_inserts_block`, `test_rerun_replaces_block`, etc. Some still apply (idempotent replace within the same marker_key), some need to flip (cross-Stop blocks accumulate now). This task surveys them, fixes assertions, and adds the new integration cases.

- [ ] **Step 1: Inventory the existing tests and their assumptions**

```bash
grep -n '^def test_' tests/test_auto_recap.py
```

For each test, decide: keep / adjust / replace. Print the inventory as a comment at the top of the file for the implementer:

| Existing test | Action |
|---------------|--------|
| `test_disabled_when_env_unset` | Keep |
| `test_disabled_without_kg_vault` | Keep |
| `test_happy_path_inserts_block` | Adjust — expect `kg-recap-sid:{sid8}-{HHMM}` marker |
| `test_rerun_replaces_block` | Replace — new semantics: a second Stop with new activity creates a SECOND block; same `marker_key` (no new activity) is a no-op |
| Any test asserting `kg-recap-sid:` with bare sid8 | Adjust to expect `{sid8}-{HHMM}` |

Run `pytest tests/test_auto_recap.py -v` to see exactly which tests fail post-Task 3; the inventory above is a starting point but the runtime list is authoritative.

- [ ] **Step 2: Adjust the happy-path test**

Find `test_happy_path_inserts_block` (use grep to locate). Where it currently asserts something like:

```python
assert f"<!-- kg-recap-sid:{sid8} -->" in daily_text
```

Change to:

```python
# After the switch to sid8-HHMM keys, the marker carries a HHMM suffix.
import re
m = re.search(rf"<!-- kg-recap-sid:({re.escape(sid8)}-\d{{4}}) -->", daily_text)
assert m, daily_text
```

Update the fake_claude output (the canned recap block the test injects) to use the new marker template — the test fixture should emit `<!-- kg-recap-sid:{sid8}-0900 -->` if it primes a log with an entry at 09:00. Locate the fake_claude payload definition (probably uses `make_fake_claude(...)`) and parameterise the marker.

- [ ] **Step 3: Extend `_canned_recap` to accept a marker_key**

The existing helper at the top of `tests/test_auto_recap.py` hard-codes the marker as `<!-- kg-recap-sid:testabcd -->`. Generalise it. Find the function (around line 149) and change its signature + body:

```python
def _canned_recap(
    folder: str = DAILY_FOLDER_REL,
    filename: str | None = None,
    insert_before: str = "",
    marker_key: str = "testabcd-2100",
    heading_hhmm: str = "21:00",
) -> str:
    if filename is None:
        filename = f"{_dt.date.today().isoformat()}.md"
    return textwrap.dedent(
        f"""\
        <!-- kg-discovery -->
        folder: {folder}
        filename: {filename}
        insert_before: {insert_before}
        <!-- /kg-discovery -->
        <!-- kg-recap-sid:{marker_key} -->
        ## Session {heading_hhmm} 〜 自動 recap テスト

        自動生成された session ブロックの例。

        ### Keep

        - テストが書ける

        ### Problem

        - (なし)

        ### Try

        - 次回も green
        <!-- /kg-recap-sid:{marker_key} -->
        """
    )
```

Apply the same change to `_canned_recap_no_discovery` — accept `marker_key` and `heading_hhmm` with the same defaults.

The module-level `CANNED_RECAP = _canned_recap()` line at the top stays as-is; existing tests that referenced it now implicitly use marker_key `testabcd-2100` instead of bare `testabcd`. Adjust those tests' assertions in the next step.

- [ ] **Step 4: Adjust existing tests' marker assertions**

For every test that asserts something containing `<!-- kg-recap-sid:testabcd -->` (or scans for that exact string), update to `<!-- kg-recap-sid:testabcd-2100 -->`. Find them with:

```bash
grep -n 'kg-recap-sid:testabcd' tests/test_auto_recap.py
```

For each hit, replace with the suffixed form. There should be a small handful.

Likewise, any test that primes a session log with arbitrary HHMM entries should ensure the canned recap's `marker_key` matches the **earliest** HHMM in the log (since `auto_recap.py` derives the marker_key from the aggregator's `Session HH:MM - HH:MM` header). Most existing tests use a single entry at `09:00`, so they need `marker_key="testabcd-0900"` and `heading_hhmm="09:00"`. Update those call sites accordingly. Example diff:

```diff
-    fake = make_fake_claude(tmp_path, CANNED_RECAP)
+    fake = make_fake_claude(
+        tmp_path,
+        _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00"),
+    )
```

If a test does not care about the marker (only checks for the discovery path or no-op behaviour), `CANNED_RECAP` is fine as long as the session log's earliest entry matches `21:00`. Easier: change those tests' log primers to `21:00`. Pick whichever is the smaller diff per test.

- [ ] **Step 5: Add the two new integration tests**

Append to `tests/test_auto_recap.py`:

```python
# --- per-Stop block accumulation --------------------------------------------

def test_two_stops_accumulate_separate_blocks(tmp_path):
    """Second Stop with new activity → new block beside the first, not in place of it."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "twostops"
    today = _dt.date.today()

    # First Stop: activity at 09:00 only.
    write_session_log(state, sid8, ["09:00 tool=Edit target=a.md"])
    fake1 = make_fake_claude(
        tmp_path / "fake1",
        _canned_recap(marker_key=f"{sid8}-0900", heading_hhmm="09:00"),
    )
    res = run_hook(
        {"session_id": sid8 + "-uuid"},
        env_extra=happy_env(vault, fake1),
        state_home=state,
    )
    assert res.returncode == 0
    daily_path = daily / f"{today.isoformat()}.md"
    first_text = daily_path.read_text()
    assert f"kg-recap-sid:{sid8}-0900" in first_text

    # Second Stop: add a 10:30 entry, clear debounce marker.
    sessions = state / "knowledge-gardener" / "sessions"
    log_path = sessions / f"{today.isoformat()}-{sid8}.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write("10:30 tool=Edit target=b.md\n")
    debounce = sessions / f".last-recap-{sid8}"
    if debounce.exists():
        debounce.unlink()

    fake2 = make_fake_claude(
        tmp_path / "fake2",
        _canned_recap(marker_key=f"{sid8}-1030", heading_hhmm="10:30"),
    )
    res = run_hook(
        {"session_id": sid8 + "-uuid"},
        env_extra=happy_env(vault, fake2),
        state_home=state,
    )
    assert res.returncode == 0
    second_text = daily_path.read_text()
    # Both blocks coexist.
    assert f"kg-recap-sid:{sid8}-0900" in second_text
    assert f"kg-recap-sid:{sid8}-1030" in second_text
    # Cursor advanced to the second block's end.
    cursor = sessions / f"{sid8}.cursor"
    assert cursor.read_text().strip() == "10:30"


def test_rerun_same_window_is_idempotent(tmp_path):
    """Stop hook re-runs with no new activity → no duplicate marker in the daily."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "idemp012"
    today = _dt.date.today()

    write_session_log(state, sid8, ["11:00 tool=Edit target=c.md"])
    fake = make_fake_claude(
        tmp_path / "fake",
        _canned_recap(marker_key=f"{sid8}-1100", heading_hhmm="11:00"),
    )
    # First run.
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake), state_home=state)
    # Clear debounce to force the second run through the pipeline.
    sessions = state / "knowledge-gardener" / "sessions"
    debounce = sessions / f".last-recap-{sid8}"
    if debounce.exists():
        debounce.unlink()
    # Second run with no new log activity → cursor at 11:00 → aggregator
    # filters everything out → no-op. The daily must not gain a duplicate.
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake), state_home=state)

    daily_path = daily / f"{today.isoformat()}.md"
    text = daily_path.read_text()
    # Marker appears at most twice (one open + one close), not four times.
    assert text.count(f"kg-recap-sid:{sid8}-1100") == 2


def test_legacy_bare_sid_block_left_untouched(tmp_path):
    """A daily note that already contains a legacy <!-- kg-recap-sid:abc12345 --> block
    (without HHMM suffix) must not be matched, replaced, or collided with by the new code."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "leg00001"
    today = _dt.date.today()
    daily_path = daily / f"{today.isoformat()}.md"
    # Seed a legacy block (note: not the sid we're about to write under).
    legacy_block = (
        "<!-- kg-recap-sid:oldlegcy -->\n"
        "## Session legacy 〜 do not touch\n"
        "legacy body\n"
        "<!-- /kg-recap-sid:oldlegcy -->\n"
    )
    daily_path.write_text(legacy_block, encoding="utf-8")

    write_session_log(state, sid8, ["14:00 tool=Edit target=d.md"])
    fake = make_fake_claude(
        tmp_path / "fake",
        _canned_recap(marker_key=f"{sid8}-1400", heading_hhmm="14:00"),
    )
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake), state_home=state)

    text = daily_path.read_text()
    assert "kg-recap-sid:oldlegcy" in text  # legacy preserved
    assert f"kg-recap-sid:{sid8}-1400" in text  # new block added
```

- [ ] **Step 6: Run the full test module**

```bash
pytest tests/test_auto_recap.py -v 2>&1 | tail -30
```

Expected: all green. Iterate on assertions / fixtures until clean. If a test surfaces a real bug in Task 3's `auto_recap.py`, fix the code, not the test.

- [ ] **Step 7: Run the entire test suite**

```bash
pytest tests/ -v 2>&1 | tail -10
```

Expected: every test green.

- [ ] **Step 8: Commit**

```bash
pre-commit run --files tests/test_auto_recap.py
git add tests/test_auto_recap.py
git commit -m "test(auto-recap): cover per-Stop block accumulation + windowed idempotency"
```

---

### Task 6: Version bump 0.12.2 → 0.13.0

**Files:**
- Modify: `package.json`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Edit all three files in one go**

`package.json`:

```diff
-  "version": "0.12.2",
+  "version": "0.13.0",
```

`.claude-plugin/plugin.json`:

```diff
-  "version": "0.12.2",
+  "version": "0.13.0",
```

`.claude-plugin/marketplace.json`:

```diff
-      "version": "0.12.2",
+      "version": "0.13.0",
```

- [ ] **Step 2: Run version-sync hook**

```bash
pre-commit run check-version-sync --files package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
```

Expected: PASS — all three at `0.13.0`.

- [ ] **Step 3: Commit and tag**

```bash
git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(release): bump 0.12.2 -> 0.13.0"
git tag v0.13.0
```

Do NOT push the tag yet — push happens after PR merge during release. (Follows the pattern in `git log --oneline -10`: bumps land on main first, then tags push.)

---

### Task 7: Final verification + PR

- [ ] **Step 1: Run the full test suite + pre-commit on the whole tree**

```bash
pytest tests/ -v
pre-commit run --all-files
```

Expected: all green.

- [ ] **Step 2: Manual smoke test (real env, opt-in)**

This is the one verification the test suite cannot give. Run a short Claude session locally with `KG_AUTO_RECAP=1`, do an `Edit`, hit Stop (let the assistant finish a turn), wait ~5 seconds, do another `Edit`, hit Stop again. Open today's daily note in the vault and confirm:

- Two `<!-- kg-recap-sid:{sid8}-{HHMM} -->` blocks with different HHMM suffixes.
- The cursor file exists at `~/.local/state/knowledge-gardener/sessions/{sid8}.cursor` with the second block's end-time.
- `git log -1` in the vault shows `water: ... daily auto-recap ({sid8}-{HHMM})`.

If anything is off, file as a fix on this branch, not as follow-up.

- [ ] **Step 3: Push branch and open PR**

```bash
git push -u origin feat/per-stop-recap-blocks
gh pr create --title "feat(auto-recap): per-Stop blocks so timeline accumulates" --body "$(cat <<'EOF'
## Summary

Implements [spec/per-stop-recap-blocks](https://github.com/Kohei-Wada/knowledge-gardener/pull/10).

- `auto_recap.py` now keys each daily-note block by `sid8-HHMM` and never overwrites a prior Stop's block.
- `recap_aggregate.py` learns `--since HH:MM` (strict greater-than) so each block summarises only the interval since the previous Stop.
- A per-session cursor at `$XDG_STATE_HOME/knowledge-gardener/sessions/{sid8}.cursor` tracks the last summarised HH:MM.
- Past `kg-recap-sid:{sid8}` blocks already in users' daily notes are untouched.

Closes the user-reported "毎回 KPT が書き直されて時系列が消える" issue.

## Test plan

- [ ] `pytest tests/ -v` green
- [ ] `pre-commit run --all-files` green
- [ ] Manual smoke test (two Stops, two blocks, cursor advanced)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Push tag after merge**

Only after the PR merges to main:

```bash
git checkout main
git pull
git push origin v0.13.0
gh release create v0.13.0 --generate-notes
```

---

## Open questions (track in PR review, not blocking)

**A. Cursor update timing on commit failure.** The plan updates `write_cursor` unconditionally after a successful file write, even if `commit_and_push` fails. This means a failed commit + next Stop produces a NEW block (different marker_key for any new activity) rather than retrying the failed commit. Trade-off: simpler code, but the failed commit's block sits uncommitted in the working tree. The vault's git status will surface it on the next manual interaction. If we want strict "cursor only after commit success", we'd need `commit_and_push` to return a bool and condition `write_cursor` on it — a small follow-up.

## Spec coverage check

| Spec section | Implemented in |
|---|---|
| Marker format `sid8-HHMM` | Task 3 (regex + marker_key derivation) + Task 4 (prompt) |
| Cursor file under sessions/ | Task 2 (path helper) + Task 3 (read/write) |
| Aggregator `--since` with strict greater-than | Task 1 |
| Aggregator empty-after-filter no-op | Task 1 (test) + Task 3 (run_aggregator no-op detection) |
| `extract_block` / `upsert_block` keyed by marker_key | Task 3 |
| Past `kg-recap-sid:{sid8}` blocks untouched | Task 3 (different marker_key = no match) + Task 5 (assertion in `test_two_stops_accumulate_separate_blocks`) |
| Retry-safe within same window | Task 5 (`test_rerun_same_window_is_idempotent`) |
| Version bump | Task 6 |
| `Session HH:MM 〜` heading consistent with marker | Task 3 (parses aggregator's `Session HH:MM - HH:MM` header) + Task 4 (prompt keeps the heading) |
