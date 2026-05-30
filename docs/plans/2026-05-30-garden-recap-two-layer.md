# garden-recap Two-Layer Alignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the manual `garden-recap` skill update the same per-session `kg-recap-sid:{sid8}` two-layer block as auto-recap, via a new headless-free `recap.manual_recap` CLI that reuses the existing aggregator, block surgery, daily-note writer, and cursor.

**Architecture:** A thin CLI (`python -m recap.manual_recap`) takes the resolved daily-note path, a session sid8, and a KPT section the assistant authored; it aggregates that session's Timeline, upserts the two-layer block (Timeline append-dedup + KPT replace), commits, and advances the cursor. `--dry-run` prints a diff for the skill's propose-then-commit step. The shared `topic_from_kpt` helper is extracted from the hook so both paths share it.

**Tech Stack:** Python 3 stdlib only. pytest. Reuses `recap.aggregate`, `recap.autorecap.block`, `recap.autorecap.daily_note`, `recap.shared.cursor`. Spec: [docs/specs/2026-05-30-garden-recap-two-layer-alignment-design.md](../specs/2026-05-30-garden-recap-two-layer-alignment-design.md).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `recap/autorecap/block.py` | block surgery + `topic_from_kpt` (moved here) | add public `topic_from_kpt` |
| `recap/autorecap/__main__.py` | Stop-hook orchestrator | use shared `topic_from_kpt` |
| `recap/manual_recap/__init__.py` | new package marker | **create** (empty) |
| `recap/manual_recap/__main__.py` | manual recap CLI | **create** |
| `skills/garden-recap/SKILL.md` | manual recap skill instructions | rewrite to drive the CLI |
| `tests/test_block.py` | block unit tests | add `topic_from_kpt` test |
| `tests/test_manual_recap.py` | CLI tests | **create** |
| `CLAUDE.md` | maintainer notes | note manual path reuses the block |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `package.json` | version | bump 0.16.1 → 0.17.0 |

**Shared signatures (use verbatim across tasks):**

```
recap.autorecap.block.topic_from_kpt(kpt_section: str) -> str
recap.manual_recap.__main__.main(argv: list[str] | None = None) -> int
  # exit codes: 0 ok (incl --dry-run) | 2 usage (no KG_VAULT / bad --kpt-file) | 3 nothing-to-recap
  # args: --sid, --daily-path, --kpt-file, --insert-before="", --dry-run, --no-commit
```

Reused as-is (already implemented + tested in v0.16.x):
- `recap.aggregate.__main__.aggregate_session(path, date, since=None) -> dict` (dict has `entry_count`, `first_hhmm`, `last_hhmm`, `timeline`)
- `recap.aggregate.__main__.list_logs_for_date(date)`, `select_logs(logs, date, sid, all_flag)`
- `recap.autorecap.block.upsert_session_block(note_text, sid8, *, start_hhmm, end_hhmm, topic, timeline_bullets, kpt_section, insert_before="")`
- `recap.autorecap.daily_note.DailyNote(vault, daily_path)` → `.apply_block(sid8, *, start_hhmm, end_hhmm, topic, timeline_bullets, kpt_section, insert_before)`, `.commit(marker_key, start_hhmm, topic)`, `.has_repo`
- `recap.shared.cursor.write_cursor(sid8, hhmm)`

---

## Task 1: extract `topic_from_kpt` to a shared helper

**Files:**
- Modify: `recap/autorecap/block.py`
- Modify: `recap/autorecap/__main__.py`
- Test: `tests/test_block.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_block.py`:

```python
from recap.autorecap.block import topic_from_kpt


def test_topic_from_kpt_uses_first_keep_bullet():
    kpt = "### KPT\n- Keep: webdav relay を deploy した\n- Problem: x\n- Try: y"
    assert topic_from_kpt(kpt) == "webdav relay を deploy した"


def test_topic_from_kpt_truncates_to_30_chars():
    long = "あ" * 50
    assert topic_from_kpt(f"### KPT\n- Keep: {long}") == "あ" * 30


def test_topic_from_kpt_empty_when_no_keep():
    assert topic_from_kpt("### KPT\n- Problem: only") == ""
```

- [ ] **Step 2: Run, verify failure**

Run: `cd <repo> && PYTHONPATH=. python -m pytest tests/test_block.py -k topic_from_kpt -v`
Expected: FAIL — `cannot import name 'topic_from_kpt'`.

- [ ] **Step 3: Add `topic_from_kpt` to block.py**

In `recap/autorecap/block.py`, add this public function (near `extract_kpt_section`):

```python
def topic_from_kpt(kpt_section: str) -> str:
    """Derive a short topic from the KPT's first `Keep:` bullet (≤30 chars)."""
    for line in kpt_section.splitlines():
        s = line.strip()
        if s.lower().startswith("- keep:"):
            return s.split(":", 1)[1].strip()[:30]
    return ""
```

- [ ] **Step 4: Point the hook at the shared helper**

In `recap/autorecap/__main__.py`: delete the `AutoRecap._topic_from_kpt` staticmethod (the `def _topic_from_kpt(...)` block) and add `topic_from_kpt` to the existing block import. The current import line is:

```python
from .block import extract_kpt_section
```

Change it to:

```python
from .block import extract_kpt_section, topic_from_kpt
```

Then change the one call site from `self._topic_from_kpt(kpt_section)` to `topic_from_kpt(kpt_section)`.

- [ ] **Step 5: Run tests, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_block.py tests/test_auto_recap.py -q`
Expected: PASS (the auto-recap topic-from-Keep behaviour is unchanged; `test_commit_subject_includes_topic_from_block_heading` still passes).

- [ ] **Step 6: Commit**

```bash
git add recap/autorecap/block.py recap/autorecap/__main__.py tests/test_block.py
git commit -m "refactor(recap): extract topic_from_kpt to block.py (shared by hook + manual)"
```

---

## Task 2: the `recap.manual_recap` CLI

**Files:**
- Create: `recap/manual_recap/__init__.py` (empty)
- Create: `recap/manual_recap/__main__.py`
- Test: `tests/test_manual_recap.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manual_recap.py`:

```python
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import subprocess
from pathlib import Path

import pytest

from recap.manual_recap.__main__ import main

KPT = "### KPT\n\n- Keep: 手動でまとめた\n- Problem: (なし)\n- Try: 次回も green\n"


def _sessions(state: Path) -> Path:
    d = state / "knowledge-gardener" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(state: Path, sid: str, lines: list[str]) -> Path:
    today = _dt.date.today().isoformat()
    p = _sessions(state) / f"{today}-{sid}.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _setup(tmp_path: Path, monkeypatch, *, git: bool = False) -> tuple[Path, Path, Path]:
    """Return (vault, daily_path, state). Sets KG_VAULT + XDG_STATE_HOME."""
    vault = tmp_path / "vault"
    daily_folder = vault / "04_DailyNotes"
    daily_folder.mkdir(parents=True)
    daily_path = daily_folder / f"{_dt.date.today().isoformat()}.md"
    state = tmp_path / "state"
    monkeypatch.setenv("KG_VAULT", str(vault))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    if git:
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *cmd], cwd=vault, check=True)
        (vault / ".gitkeep").write_text("")
        subprocess.run(["git", "add", "-A"], cwd=vault, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)
    return vault, daily_path, state


def _kpt_file(tmp_path: Path, body: str = KPT) -> Path:
    p = tmp_path / "kpt.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_create_block_when_absent(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md", "09:05 tool=Bash target=git commit -m x"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily),
               "--kpt-file", str(_kpt_file(tmp_path)), "--no-commit"])
    assert rc == 0
    text = daily.read_text()
    assert "<!-- kg-recap-sid:manual01 -->" in text
    assert "### Timeline" in text
    assert "- 09:00  Edit a.md" in text
    assert "Keep: 手動でまとめた" in text
    # cursor advanced to session end
    assert (state / "knowledge-gardener" / "sessions" / "manual01.cursor").read_text().strip() == "09:05"


def test_updates_existing_auto_block_coalescing(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    # an auto-written block already exists for this sid, with one Timeline bullet + a different KPT
    daily.write_text(
        "<!-- kg-recap-sid:manual01 -->\n"
        "## Session 09:00〜09:00  auto topic\n\n"
        "### Timeline\n- 09:00  Edit a.md\n\n"
        "### KPT\n- Keep: auto が書いた\n<!-- /kg-recap-sid:manual01 -->\n",
        encoding="utf-8",
    )
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md", "09:30 tool=Write target=b.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily),
               "--kpt-file", str(_kpt_file(tmp_path)), "--no-commit"])
    assert rc == 0
    text = daily.read_text()
    assert text.count("<!-- kg-recap-sid:manual01 -->") == 1          # still one block
    assert "- 09:00  Edit a.md" in text                               # prior bullet kept (deduped)
    assert "- 09:30  Write b.md" in text                              # new bullet appended
    assert "Keep: 手動でまとめた" in text and "Keep: auto が書いた" not in text  # KPT replaced
    assert "## Session 09:00〜09:30  手動でまとめた" in text            # end + topic refreshed


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--sid", "manual01", "--daily-path", str(daily),
                   "--kpt-file", str(_kpt_file(tmp_path)), "--dry-run"])
    assert rc == 0
    out = buf.getvalue()
    assert "kg-recap-sid:manual01" in out          # diff shows the new block
    assert "+### Timeline" in out or "### Timeline" in out
    assert not daily.exists()                       # nothing written
    assert not (state / "knowledge-gardener" / "sessions" / "manual01.cursor").exists()  # cursor untouched


def test_empty_session_returns_nonzero(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    # no session log written at all
    rc = main(["--sid", "nolog999", "--daily-path", str(daily),
               "--kpt-file", str(_kpt_file(tmp_path)), "--no-commit"])
    assert rc == 3
    assert not daily.exists()


def test_legacy_hhmm_block_not_collided(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    daily.write_text(
        "<!-- kg-recap-sid:manual01-1400 -->\n## Session 14:00 〜 legacy\nbody\n"
        "<!-- /kg-recap-sid:manual01-1400 -->\n",
        encoding="utf-8",
    )
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily),
               "--kpt-file", str(_kpt_file(tmp_path)), "--no-commit"])
    assert rc == 0
    text = daily.read_text()
    assert "kg-recap-sid:manual01-1400" in text                 # legacy preserved
    assert text.count("<!-- kg-recap-sid:manual01 -->") == 1     # new bare block added


def test_no_kg_vault_returns_usage_error(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("KG_VAULT", raising=False)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily),
               "--kpt-file", str(_kpt_file(tmp_path)), "--no-commit"])
    assert rc == 2


def test_commits_when_repo_and_not_no_commit(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch, git=True)
    monkeypatch.setenv("KG_AUTO_RECAP_NO_PUSH", "1")  # never push in tests
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily),
               "--kpt-file", str(_kpt_file(tmp_path))])
    assert rc == 0
    subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=vault,
                          capture_output=True, text=True, check=True).stdout.strip()
    assert subj.startswith("water:") and "手動でまとめた" in subj
```

- [ ] **Step 2: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_manual_recap.py -q`
Expected: FAIL — `No module named 'recap.manual_recap'`.

- [ ] **Step 3: Create the package + CLI**

Create empty `recap/manual_recap/__init__.py`:

```python
```

Create `recap/manual_recap/__main__.py`:

```python
#!/usr/bin/env python3
"""Manual recap CLI — drive the two-layer kg-recap-sid block from garden-recap.

Unlike the Stop hook (recap.autorecap), this is invoked interactively by the
garden-recap skill: the assistant authors the KPT, so there is no headless
claude call. It reuses the same aggregator, block surgery, daily-note writer,
and cursor as auto-recap, so manual and auto recaps converge on one block.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import os
import pathlib
import sys

from ..aggregate.__main__ import aggregate_session, list_logs_for_date, select_logs
from ..autorecap.block import topic_from_kpt, upsert_session_block
from ..autorecap.daily_note import DailyNote
from ..shared.cursor import write_cursor


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update the per-session two-layer recap block (manual garden-recap path)."
    )
    p.add_argument("--sid", required=True, help="Session sid8 to recap.")
    p.add_argument("--daily-path", required=True, help="Absolute path to today's daily note (resolved by the skill).")
    p.add_argument("--kpt-file", required=True, help="File containing the ### KPT section to write.")
    p.add_argument("--insert-before", default="", help="Heading to insert a NEW block before (default: append at EOF).")
    p.add_argument("--dry-run", action="store_true", help="Print the daily-note diff and exit without writing.")
    p.add_argument("--no-commit", action="store_true", help="Write the file but skip git commit/push.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    vault = os.environ.get("KG_VAULT")
    if not vault:
        sys.stderr.write("KG_VAULT unset\n")
        return 2
    try:
        kpt = pathlib.Path(args.kpt_file).read_text(encoding="utf-8").strip()
    except OSError as e:
        sys.stderr.write(f"cannot read --kpt-file: {e}\n")
        return 2
    if not kpt:
        sys.stderr.write("empty KPT\n")
        return 2

    today = _dt.date.today()
    selected = select_logs(list_logs_for_date(today), today, args.sid, False)
    if not selected:
        sys.stderr.write(f"no session log for sid {args.sid} on {today.isoformat()} — nothing to recap\n")
        return 3
    agg = aggregate_session(selected[0], today)
    if not agg.get("entry_count"):
        sys.stderr.write("session has no captured tool calls — nothing to recap\n")
        return 3

    start, end = agg["first_hhmm"], agg["last_hhmm"]
    timeline = agg["timeline"]
    topic = topic_from_kpt(kpt)
    daily_path = pathlib.Path(args.daily_path)
    existing = daily_path.read_text(encoding="utf-8") if daily_path.is_file() else ""
    new = upsert_session_block(
        existing, args.sid, start_hhmm=start, end_hhmm=end, topic=topic,
        timeline_bullets=timeline, kpt_section=kpt, insert_before=args.insert_before,
    )

    if args.dry_run:
        diff = difflib.unified_diff(
            existing.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=str(daily_path), tofile=f"{daily_path} (new)",
        )
        sys.stdout.write("".join(diff))
        return 0

    note = DailyNote(pathlib.Path(vault), daily_path)
    changed = note.apply_block(
        args.sid, start_hhmm=start, end_hhmm=end, topic=topic,
        timeline_bullets=timeline, kpt_section=kpt, insert_before=args.insert_before,
    )
    if changed and not args.no_commit and note.has_repo:
        note.commit(args.sid, start, topic or None)
    write_cursor(args.sid, end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_manual_recap.py -v`
Expected: PASS (all 7). If `test_dry_run_writes_nothing`'s `+### Timeline` assertion is brittle (diff context formatting), the fallback `or "### Timeline" in out` keeps it green.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=. python -m pytest tests/ -q`
Expected: PASS (no regression).

- [ ] **Step 6: Commit**

```bash
git add recap/manual_recap/__init__.py recap/manual_recap/__main__.py tests/test_manual_recap.py
git commit -m "feat(recap): recap.manual_recap CLI — manual garden-recap updates the two-layer block"
```

---

## Task 3: rewrite the garden-recap skill to drive the CLI

**Files:**
- Modify: `skills/garden-recap/SKILL.md`

This is a skill-instruction (Markdown) change — no automated test; verify by reading. Read the current `skills/garden-recap/SKILL.md` in full first, then rewrite **Step 2 (Inventory)**, **Step 4 (Draft)**, **Step 5 (Propose)**, **Step 6 (Apply)**, **Step 7 (Commit)** so the flow becomes:

- [ ] **Step 1: Rewrite the process steps**

Replace the body of Steps 2–7 with this flow (keep Step 1 Pre-flight and the When-to-Use / When-NOT / Edge-Cases / Key-Principles sections, lightly updated for consistency):

1. **Identify the session & gather the Timeline.** Run `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m recap.aggregate --json` (default = latest session). Parse `sessions[0].sid8`. If `sessions` is empty or `entry_count` is 0 → **no capture log**: fall back to the current recollection-based template recap (the prior behaviour — keep that text under a clearly-labelled "No-log fallback" subsection) and stop following the two-layer path.
2. **Author the KPT.** From the full conversation (richer than the hook's transcript slice), write a `### KPT` section using the vault's KPT convention (Keep / Problem / Try, per the README/template). Cap each list at ~5 bullets. Facts for "what happened" come from the Timeline / conversation / `git log`; Keep/Problem/Try are your interpretation. Write it to a temp file, e.g. `"$(mktemp).md"`.
3. **Preview (Propose, Don't Commit).** Run, with the daily-note path resolved in Step 1:
   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m recap.manual_recap \
     --sid <sid8> --daily-path <abs daily path> --kpt-file <temp> --dry-run
   ```
   Show the printed diff to the user with the one-line rationale "Capturing today's session into the per-session recap block so the next session can pick up context." Trigger phrases ("wrap up and write it" / "ここまでまとめて書いて") count as approval.
4. **Apply on approval.** Re-run the same command **without `--dry-run`**. The CLI writes the block atomically, commits (`water: <date> <HH:MM> 〜 <topic>`), and advances the per-session cursor so a later auto `Stop` inherits your KPT instead of overwriting it.

Update the skill's "## Process" intro and the `recap.aggregate` example block (lines that document the old human-text aggregator output) to reflect that the two-layer block is now the output shape, and that block assembly is delegated to `recap.manual_recap`. Keep the "Evidence over recollection" and "Preserve prior content on append" principles — they still hold (the CLI's Timeline dedup + KPT-only replace enforce them mechanically).

- [ ] **Step 2: Verify the skill references resolve**

Run: `PYTHONPATH=. python -m pytest tests/ -q` (sanity, unaffected) and `pre-commit run --files skills/garden-recap/SKILL.md`
Expected: tests pass; the skill-frontmatter and skill-refs pre-commit hooks pass.

- [ ] **Step 3: Commit**

```bash
git add skills/garden-recap/SKILL.md
git commit -m "feat(garden-recap): drive the two-layer block via recap.manual_recap"
```

---

## Task 4: docs + version bump

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `package.json`

- [ ] **Step 1: Note the manual path in CLAUDE.md**

In `CLAUDE.md`, in the recap/skills discussion, add a sentence that `garden-recap` now reuses the same two-layer `kg-recap-sid` block as the `Stop` hook via the `recap.manual_recap` CLI (manual wrap-ups coalesce with the auto block; no headless claude call because the assistant authors the KPT).

- [ ] **Step 2: Bump version 0.16.1 → 0.17.0**

Run: `scripts/bump-version.sh minor`
Expected: edits the three version files to `0.17.0`, commits `chore(release): bump 0.16.1 -> 0.17.0`, tags `v0.17.0`. (This is the canonical release step; do NOT hand-edit the version files.)

Note: `bump-version.sh` aborts on a dirty tree, so run it only after Tasks 1–3 are committed and `CLAUDE.md` is committed. Sequence:

```bash
git add CLAUDE.md && git commit -m "docs(claude): note garden-recap reuses the two-layer block"
scripts/bump-version.sh minor
```

- [ ] **Step 3: Final verification**

Run: `PYTHONPATH=. python -m pytest tests/ -q && pre-commit run --all-files`
Expected: all tests pass; the version-match hook passes (all three files at 0.17.0).

Tag push (`git push origin main v0.17.0`) is left for the human after the PR merges — it is NOT part of this plan (release happens post-merge, per the repo's convention noted in #24/#25).

---

## Self-review notes

- Spec coverage: CLI (Task 2) ✓, skill rewrite (Task 3) ✓, `topic_from_kpt` extraction (Task 1) ✓, cursor advance (Task 2 code + test) ✓, dry-run propose (Task 2) ✓, create/update/legacy/empty (Task 2 tests) ✓, no-log fallback (Task 3 step 1) ✓, version bump (Task 4) ✓.
- The CLI is headless-free: it never imports or calls `claude`; the KPT comes from `--kpt-file`. ✓
- `topic_from_kpt` signature is identical to the hook's old private impl, so auto-recap behaviour is unchanged. ✓
