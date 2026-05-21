"""Subprocess-based tests for skills/garden-recap/auto_recap.py.

These tests mock the headless `claude` binary via $KG_AUTO_RECAP_CLAUDE_CMD,
pointing it at a small shell script that prints a canned recap block. The
real Claude is never invoked.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_RECAP = REPO_ROOT / "skills" / "garden-recap" / "auto_recap.py"

# Neutral layout the test vault uses (created by make_vault). Names are
# intentionally generic — knowledge-gardener is format-agnostic, so the test
# vault must not assume any real-world vault's folder naming.
DAILY_FOLDER_REL = "daily"
DAILY_TEMPLATE_REL = "template.md"


def happy_env(vault: Path, fake_claude: Path) -> dict[str, str]:
    """Env vars needed for a happy-path auto-recap run against the test vault."""
    return {
        "KG_AUTO_RECAP": "1",
        "KG_VAULT": str(vault),
        "KG_AUTO_RECAP_CLAUDE_CMD": str(fake_claude),
        "KG_DAILY_FOLDER": DAILY_FOLDER_REL,
        "KG_DAILY_TEMPLATE": DAILY_TEMPLATE_REL,
    }


def make_fake_claude(tmp_path: Path, output: str, exit_code: int = 0, sleep: float = 0.0) -> Path:
    """Create a fake `claude` binary that ignores its args and prints `output`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_claude.sh"
    body = "#!/usr/bin/env bash\n"
    if sleep:
        body += f"sleep {sleep}\n"
    # use printf to preserve exact content
    body += "cat <<'KGEOF'\n" + output + "\nKGEOF\n"
    body += f"exit {exit_code}\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return script


def make_vault(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Set up a minimal vault with README + daily-notes folder + template. Returns (vault, daily_folder, repo_root).

    Folder names here are deliberately neutral (no real-world vault layout
    references); auto-recap learns the layout from env vars (KG_DAILY_FOLDER,
    KG_DAILY_TEMPLATE) so it never needs to know names like '04_DailyNotes'.
    """
    repo = tmp_path / "vault-repo"
    vault = repo / "vault"
    daily = vault / DAILY_FOLDER_REL
    repo.mkdir()
    vault.mkdir()
    daily.mkdir()
    (vault / "README.md").write_text(
        textwrap.dedent(
            f"""\
            # Vault README

            ## Conventions
            - Daily notes live in `{DAILY_FOLDER_REL}/`, filename `YYYY-MM-DD.md`.
            - KPT sub-sections (Keep / Problem / Try). Try must not be omitted.
            """
        )
    )
    (vault / DAILY_TEMPLATE_REL).write_text(
        textwrap.dedent(
            """\
            ---
            title: {{date}}
            ---

            ## KPT

            ### Keep

            -

            ### Problem

            -

            ### Try

            -
            """
        )
    )
    # git init so commit/push path is exercised (we'll skip push via env)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    # initial commit so the working tree is well-formed
    (repo / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return vault, daily, repo


def write_session_log(state_home: Path, sid8: str, lines: list[str]) -> Path:
    sessions = state_home / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    p = sessions / f"{today}-{sid8}.log"
    p.write_text("\n".join(lines) + "\n")
    return p


def run_hook(payload: dict, *, env_extra: dict[str, str], state_home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(state_home)
    env["HOME"] = str(state_home.parent / "fakehome")
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    env["KG_AUTO_RECAP_NO_PUSH"] = "1"  # never push during tests
    for k, v in env_extra.items():
        env[k] = v
    return subprocess.run(
        [sys.executable, str(AUTO_RECAP)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def assert_continue(stdout: str) -> None:
    obj = json.loads(stdout.strip().splitlines()[-1])
    assert obj.get("continue") is True
    assert obj.get("suppressOutput") is True


def _canned_recap(
    folder: str = DAILY_FOLDER_REL,
    filename: str | None = None,
    insert_before: str = "",
    marker_key: str = "testabcd-2100",
    heading_hhmm: str = "21:00",
) -> str:
    """Build a canned Claude output: kg-discovery block + kg-recap-sid block.

    Mirrors the new (PR #8) output contract where Claude returns discovery
    metadata alongside the recap. Tests can vary the discovered folder/filename
    or omit them entirely to exercise the no-discovery path.
    """
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


def _canned_recap_no_discovery(
    marker_key: str = "testabcd-2100",
    heading_hhmm: str = "21:00",
) -> str:
    """Canned output with NO kg-discovery block — exercises the no-discovery path."""
    return textwrap.dedent(
        f"""\
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


CANNED_RECAP = _canned_recap()


# --- opt-in gate -------------------------------------------------------------

def test_no_op_when_env_unset(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra={"KG_VAULT": str(vault)},  # KG_AUTO_RECAP NOT set
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_no_vault(tmp_path):
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra={"KG_AUTO_RECAP": "1"},  # KG_VAULT unset
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


def test_no_op_when_no_session_log(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    fake = make_fake_claude(tmp_path, CANNED_RECAP)
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


# --- discovery / env-var configuration --------------------------------------

def test_writes_via_discovery_when_env_unset(tmp_path):
    """With KG_DAILY_FOLDER unset, Claude's kg-discovery block drives the write."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00"))
    env = happy_env(vault, fake)
    # remove both env keys so only the kg-discovery block can resolve the path
    del env["KG_DAILY_FOLDER"]
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert (daily / f"{today}.md").exists(), "discovery-driven write should have created the daily note"


def test_no_op_when_env_unset_and_no_discovery(tmp_path):
    """No env override and no kg-discovery block → no-op (never guess a folder)."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap_no_discovery())
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_daily_folder_path_invalid(tmp_path):
    """When KG_DAILY_FOLDER points at a missing path, auto-recap degrades to no-op."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, CANNED_RECAP)
    env = happy_env(vault, fake)
    env["KG_DAILY_FOLDER"] = "nonexistent-folder"
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_logs_hint_when_discovery_prefixes_vault_basename(tmp_path):
    """When discovery emits folder=<vault.basename>/<sub>, log a diagnostic hint.

    Reproduces the failure mode where a tree-format README's top node (which
    represents the vault root itself) is mistakenly included as a path prefix,
    producing a doubled path that does not exist. Auto-recap stays a no-op,
    but the log gains a hint line so the user can clarify their README or
    the discovery prompt.
    """
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    bad_folder = f"{vault.name}/{DAILY_FOLDER_REL}"
    fake = make_fake_claude(
        tmp_path,
        _canned_recap(folder=bad_folder, marker_key="testabcd-0900", heading_hhmm="09:00"),
    )
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]  # force the discovery path
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()
    log_path = (
        tmp_path / "fakehome" / ".local" / "state" / "knowledge-gardener" / "auto-recap.log"
    )
    log_content = log_path.read_text(encoding="utf-8")
    assert "daily folder does not exist" in log_content
    assert "hint:" in log_content
    assert vault.name in log_content


def test_env_override_wins_over_discovery(tmp_path):
    """When both env KG_DAILY_FOLDER and kg-discovery folder are set, env wins."""
    vault, _, _ = make_vault(tmp_path)
    # second folder the env will point to (different from the one Claude discovers)
    alt = vault / "alt-daily"
    alt.mkdir()
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    # Claude discovers DAILY_FOLDER_REL ("daily") but env points at "alt-daily"
    fake = make_fake_claude(tmp_path, _canned_recap(folder=DAILY_FOLDER_REL, marker_key="testabcd-0900", heading_hhmm="09:00"))
    env = happy_env(vault, fake)
    env["KG_DAILY_FOLDER"] = "alt-daily"
    # the discovery's filename still drives the filename (no KG_DAILY_FILENAME set)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    today = _dt.date.today().isoformat()
    assert (alt / f"{today}.md").exists(), "env override should have placed the note under alt-daily"
    assert not (vault / DAILY_FOLDER_REL / f"{today}.md").exists()


def test_insert_before_anchor_places_block_above_heading(tmp_path):
    """KG_DAILY_INSERT_BEFORE makes the recap block land above the named heading."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    today = _dt.date.today().isoformat()
    # pre-seed the daily note with a trailing section the anchor should land above
    (daily / f"{today}.md").write_text(
        "## Existing top\n\nsome body\n\n## Carry over\n\n- left for tomorrow\n",
        encoding="utf-8",
    )
    fake = make_fake_claude(tmp_path, _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00"))
    env = happy_env(vault, fake)
    env["KG_DAILY_INSERT_BEFORE"] = "## Carry over"
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    content = (daily / f"{today}.md").read_text(encoding="utf-8")
    block_idx = content.index("<!-- kg-recap-sid:testabcd-0900 -->")
    anchor_idx = content.index("## Carry over")
    assert block_idx < anchor_idx, "recap block should land before the anchor heading"
    assert "left for tomorrow" in content, "anchor section content must survive"


# --- happy path --------------------------------------------------------------

def test_writes_session_block_on_happy_path(tmp_path):
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(
        state,
        "testabcd",
        ["09:00 tool=Edit target=a.md", "09:05 tool=Bash target=git commit -m x"],
    )
    fake = make_fake_claude(tmp_path, _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00"))
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    note = daily / f"{today}.md"
    assert note.exists()
    content = note.read_text()
    assert "<!-- kg-recap-sid:testabcd-0900 -->" in content
    assert "自動 recap テスト" in content
    assert "<!-- /kg-recap-sid:testabcd-0900 -->" in content


def test_idempotent_replaces_existing_block(tmp_path):
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    canned = _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00")
    fake1 = make_fake_claude(tmp_path / "v1", canned)
    env = happy_env(vault, fake1)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)

    # second invocation with different body but same sid → should REPLACE
    updated_recap = canned.replace("自動 recap テスト", "更新後のテスト")
    fake2 = make_fake_claude(tmp_path / "v2", updated_recap)
    # bypass debounce by clearing marker; also clear cursor so aggregator
    # re-processes the full log and produces the same marker_key (testabcd-0900)
    sessions = state / "knowledge-gardener" / "sessions"
    debounce = sessions / ".last-recap-testabcd"
    if debounce.exists():
        debounce.unlink()
    cursor = sessions / "testabcd.cursor"
    if cursor.exists():
        cursor.unlink()

    env["KG_AUTO_RECAP_CLAUDE_CMD"] = str(fake2)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    today = _dt.date.today().isoformat()
    content = (daily / f"{today}.md").read_text()
    # one occurrence of the marker pair, content updated
    assert content.count("<!-- kg-recap-sid:testabcd-0900 -->") == 1
    assert "更新後のテスト" in content
    assert "自動 recap テスト" not in content


# --- error handling ---------------------------------------------------------

def test_no_op_when_claude_output_missing_markers(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, "just some text, no markers")
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_claude_nonzero_exit(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, "", exit_code=2)
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_claude_binary_missing(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra={
            **happy_env(vault, Path("/nonexistent/path/to/claude")),
        },
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


def test_malformed_stdin_does_not_crash(tmp_path):
    env = os.environ.copy()
    env["KG_AUTO_RECAP"] = "1"
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["HOME"] = str(tmp_path / "home")
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [sys.executable, str(AUTO_RECAP)],
        input="not json {",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


# --- debounce ---------------------------------------------------------------

def test_debounce_skips_rapid_reinvocation(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    canned = _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00")
    fake = make_fake_claude(tmp_path, canned)
    env = happy_env(vault, fake)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    today = _dt.date.today().isoformat()
    first_mtime = (daily / f"{today}.md").stat().st_mtime

    # immediate re-invocation → debounce should skip
    time.sleep(0.1)
    # alter the fake output so we can detect if it ran
    fake2 = make_fake_claude(tmp_path / "v2", canned.replace("自動 recap テスト", "should not appear"))
    env["KG_AUTO_RECAP_CLAUDE_CMD"] = str(fake2)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)

    content = (daily / f"{today}.md").read_text()
    assert "should not appear" not in content
    assert "自動 recap テスト" in content


# --- git commit -------------------------------------------------------------

def test_commit_subject_includes_topic_from_block_heading(tmp_path):
    """Commit subject should pull `<topic>` from the block's `## Session HH:MM 〜 <topic>` heading."""
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap(marker_key="testabcd-0900", heading_hhmm="09:00"))
    run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    today = _dt.date.today().isoformat()
    # canned recap's heading is `## Session 09:00 〜 自動 recap テスト` → topic = `自動 recap テスト`
    assert proc.stdout.strip() == f"water: {today} 09:00 〜 自動 recap テスト"


def test_commit_subject_falls_back_when_heading_missing(tmp_path):
    """If the block has no `## Session HH:MM 〜 <topic>` heading, fall back to marker-key form."""
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "noheadng", ["09:00 tool=Edit target=a.md"])
    today = _dt.date.today().isoformat()
    # Build a recap block without the conventional `## Session ... 〜 ...` heading.
    headless_block = textwrap.dedent(
        f"""\
        <!-- kg-discovery -->
        folder: {DAILY_FOLDER_REL}
        filename: {today}.md
        insert_before:
        <!-- /kg-discovery -->
        <!-- kg-recap-sid:noheadng-0900 -->
        ## Some other heading

        body without the expected session line.
        <!-- /kg-recap-sid:noheadng-0900 -->
        """
    )
    fake = make_fake_claude(tmp_path, headless_block)
    run_hook(
        {"session_id": "noheadng-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == f"water: {today} daily auto-recap (noheadng-0900)"


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
    # Marker appears exactly twice (one open + one close), not four.
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
