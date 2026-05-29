"""Unit tests for the class-based internals of auto_recap.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_RECAP_PATH = REPO_ROOT / "skills" / "garden-recap" / "auto_recap.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("auto_recap_under_test", AUTO_RECAP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_recap_context_from_hook_returns_none_when_env_unset(monkeypatch):
    mod = _load_module()
    monkeypatch.delenv("KG_AUTO_RECAP", raising=False)
    ctx = mod.RecapContext.from_hook('{"session_id": "abcd1234ef"}', dict_env={})
    assert ctx is None


def test_recap_context_from_hook_builds_facts(monkeypatch, tmp_path):
    mod = _load_module()
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {"KG_AUTO_RECAP": "1", "KG_VAULT": str(vault)}
    ctx = mod.RecapContext.from_hook('{"session_id": "abcd1234efgh"}', dict_env=env)
    assert ctx is not None
    assert ctx.sid8 == "abcd1234"
    assert ctx.vault == vault
    assert len(ctx.today_str) == 10  # YYYY-MM-DD


def test_session_aggregator_returns_none_when_no_sessions(monkeypatch, tmp_path):
    mod = _load_module()
    monkeypatch.setattr(mod, "run_aggregator", lambda sid8, since=None: None)
    ctx = mod.RecapContext(sid8="abcd1234", vault=tmp_path, today_str="2026-05-29", since=None)
    agg = mod.SessionAggregator(ctx).aggregate()
    assert agg is None


def test_session_aggregator_parses_window(monkeypatch, tmp_path):
    mod = _load_module()
    fake_out = (
        "# Sessions on 2026-05-29\n1 session(s) found.\n\n"
        "## Session 09:00 - 09:30 (sid8: abcd1234)\n"
        "Duration: 30m, 5 captured tool calls.\n"
    )
    monkeypatch.setattr(mod, "run_aggregator", lambda sid8, since=None: fake_out)
    ctx = mod.RecapContext(sid8="abcd1234", vault=tmp_path, today_str="2026-05-29", since=None)
    agg = mod.SessionAggregator(ctx).aggregate()
    assert agg is not None
    assert agg.text == fake_out
    assert agg.start_hhmm == "09:00"
    assert agg.end_hhmm == "09:30"


def _ctx_with_vault(mod, tmp_path):
    vault = tmp_path / "vault"
    (vault / "04_DailyNotes").mkdir(parents=True)
    return mod.RecapContext(sid8="abcd1234", vault=vault, today_str="2026-05-29", since=None), vault


def test_resolver_pre_resolve_hits_via_env(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    monkeypatch.setenv("KG_DAILY_FOLDER", "04_DailyNotes")
    monkeypatch.setenv("KG_DAILY_FILENAME", "2026-05-29.md")
    r = mod.DailyNoteResolver(ctx)
    pre = r.pre_resolve()
    assert pre is not None
    daily_path, _ = pre
    assert daily_path == vault / "04_DailyNotes" / "2026-05-29.md"
    assert r.pre_resolved is True


def test_resolver_pre_resolve_misses_without_env_or_cache(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.setattr(mod, "read_discovery_cache", lambda h: None)
    r = mod.DailyNoteResolver(ctx)
    assert r.pre_resolve() is None
    assert r.pre_resolved is False


def test_resolver_resolve_from_discovery(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    r = mod.DailyNoteResolver(ctx)
    claude_out = (
        "<!-- kg-discovery -->\n"
        "folder: 04_DailyNotes\n"
        "filename: 2026-05-29.md\n"
        "insert_before:\n"
        "<!-- /kg-discovery -->\n"
    )
    res = r.resolve_from_discovery(claude_out)
    assert res is not None
    daily_path, insert_before = res
    assert daily_path == vault / "04_DailyNotes" / "2026-05-29.md"
    assert insert_before == ""


def test_resolver_persist_cache_writes_on_miss(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.setattr(mod, "read_discovery_cache", lambda h: None)
    monkeypatch.setattr(mod, "compute_readme_hash", lambda v: "deadbeef")
    written = {}
    monkeypatch.setattr(mod, "write_discovery_cache", lambda h, d: written.update({"hash": h, "discovery": d}))
    r = mod.DailyNoteResolver(ctx)
    r.pre_resolve()  # miss → pre_resolved False
    r.resolve_from_discovery(
        "<!-- kg-discovery -->\nfolder: 04_DailyNotes\nfilename: 2026-05-29.md\nfilename_pattern: {date}.md\n<!-- /kg-discovery -->\n"
    )
    r.persist_cache()
    assert written["hash"] == "deadbeef"
    assert written["discovery"]["folder"] == "04_DailyNotes"


def test_daily_note_apply_block_writes_file(tmp_path):
    mod = _load_module()
    vault = tmp_path / "vault"
    folder = vault / "04_DailyNotes"
    folder.mkdir(parents=True)
    daily_path = folder / "2026-05-29.md"
    note = mod.DailyNote(vault, daily_path)
    block = "<!-- kg-recap-sid:abcd1234-0900 -->\n## Session 09:00 〜 x\n<!-- /kg-recap-sid:abcd1234-0900 -->"
    changed = note.apply_block("abcd1234-0900", block, insert_before="")
    assert changed is True
    assert "kg-recap-sid:abcd1234-0900" in daily_path.read_text()


def test_daily_note_apply_block_noop_when_identical(tmp_path):
    mod = _load_module()
    vault = tmp_path / "vault"
    folder = vault / "04_DailyNotes"
    folder.mkdir(parents=True)
    daily_path = folder / "2026-05-29.md"
    note = mod.DailyNote(vault, daily_path)
    block = "<!-- kg-recap-sid:abcd1234-0900 -->\nx\n<!-- /kg-recap-sid:abcd1234-0900 -->"
    assert note.apply_block("abcd1234-0900", block, "") is True
    # second identical apply → no change
    assert note.apply_block("abcd1234-0900", block, "") is False
