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
