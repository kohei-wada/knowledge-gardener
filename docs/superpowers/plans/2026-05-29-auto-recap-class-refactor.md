# auto_recap.py Class Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `skills/garden-recap/auto_recap.py`'s monolithic `main()` into role-focused classes (`RecapContext`, `SessionAggregator`, `DailyNoteResolver`, `DailyNote`, `AutoRecap`) so the Stop-hook pipeline reads as an outline, with zero external behavior change.

**Architecture:** Behavior-preserving refactor. The existing pure helper functions stay as module-level functions. New classes wrap the stateful clusters; `AutoRecap.run()` orchestrates them with the same early-return no-op flow as today's `main()`. The 30+ subprocess tests in `tests/test_auto_recap.py` are the behavior-preservation guarantee and must stay green at every commit. New unit tests are added only for `DailyNoteResolver`.

**Tech Stack:** Python 3 (stdlib only), pytest, pre-commit.

**Spec:** [docs/specs/2026-05-29-auto-recap-class-refactor-design.md](../../specs/2026-05-29-auto-recap-class-refactor-design.md)

---

## Working agreement (read before starting)

- **Green at every commit.** After every task, `python -m pytest tests/test_auto_recap.py tests/test_recap_aggregate.py -q` MUST pass before committing. This suite is the contract.
- **No behavior change.** If a test changes meaning, you did something wrong — stop and reconsider, do not edit the test to match new behavior.
- **Order matters.** Build leaf classes first (no dependencies), wire the orchestrator last. Each task leaves the file working — classes are introduced alongside the still-callable `main()`, and `main()` is slimmed only once its collaborators exist.
- **Keep these module functions** (do not move into classes): `emit_continue`, `log`, `call_claude`, `compose_prompt`, `load_vault_context`, `read_text`, `_resolve_under_vault`, `extract_block`, `extract_topic`, `read_cursor`, `write_cursor`, `plugin_root`, `vault_root`, all `*_RE` regexes, and the `kg_paths` wrapper functions (`session_log_path`, `debounce_marker`, `cursor_path`, `discovery_cache_path`).

---

## File structure

| File | Change | Responsibility after |
|------|--------|----------------------|
| `skills/garden-recap/auto_recap.py` | Modify | Module functions (kept) + 5 new classes + thin `main()` that builds `AutoRecap` and calls `run()` |
| `tests/test_auto_recap.py` | Unchanged | Subprocess behavior contract (must stay green) |
| `tests/test_daily_note_resolver.py` | Create | Unit tests importing `DailyNoteResolver` directly |

All classes live in the single `auto_recap.py` module (the hook is invoked as one script; splitting into multiple files would complicate the `sys.path` / `CLAUDE_PLUGIN_ROOT` resolution for no benefit). Within the file, order top-to-bottom: kept helpers → `RecapContext` → `SessionAggregator` → `DailyNoteResolver` → `DailyNote` → `AutoRecap` → `main()`.

---

## Task 1: Introduce `RecapContext` (immutable per-run facts)

**Files:**
- Modify: `skills/garden-recap/auto_recap.py` (add class after `vault_root`, before `main`)

`RecapContext` holds the facts resolved once at the top of a run: `sid8`, `vault` (Path), `today_str`, `since`. A classmethod `from_hook(raw_stdin, env)` returns a `RecapContext` or `None` (the no-op signal) by replicating `main()` lines 581–627 logic *up to and including* reading the cursor — but NOT debounce, NOT session-log existence (those stay in the orchestrator because they short-circuit before/independently of building context… see note).

> Note on ordering: today's `main()` does debounce (L606) and session-log check (L622) *between* env-gate and cursor read. To keep `RecapContext` cohesive (just "the facts"), `from_hook` does env-gate + payload parse + vault resolve + sid8 + cursor read. Debounce and session-log existence move to `AutoRecap.run()` as separate guard steps (Task 5). This reordering is safe: reading the cursor is side-effect-free, and the guards still run before any aggregation or LLM call. The subprocess tests assert on outcomes (no-op vs write), not on the internal order of these guards.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_auto_recap.py` is NOT allowed (keep it unchanged). Instead create the new unit test file early for context types. Create `tests/test_daily_note_resolver.py` with a placeholder import test first:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_note_resolver.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'RecapContext'`

- [ ] **Step 3: Write minimal implementation**

Add to `auto_recap.py` after `vault_root()` (note: `from_hook` reads env from an injected dict to stay unit-testable; production passes `os.environ`):

```python
import dataclasses


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_note_resolver.py tests/test_auto_recap.py -q`
Expected: new unit tests PASS; all subprocess tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/garden-recap/auto_recap.py tests/test_daily_note_resolver.py
git commit -m "refactor(auto-recap): add RecapContext for per-run facts" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Introduce `SessionAggregator`

**Files:**
- Modify: `skills/garden-recap/auto_recap.py` (add class after `RecapContext`; add `Aggregation` dataclass)

Wraps `run_aggregator` + `parse_session_window` into one call returning an `Aggregation(text, start_hhmm, end_hhmm)` or `None`. The existing module functions `run_aggregator` and `parse_session_window` stay (the class calls them) — this keeps their current tests/behavior intact and the class thin.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_daily_note_resolver.py`:

```python
def test_session_aggregator_returns_none_when_no_sessions(monkeypatch, tmp_path):
    mod = _load_module()
    # run_aggregator returns None when aggregator yields no sessions; stub it.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_note_resolver.py::test_session_aggregator_parses_window -v`
Expected: FAIL with `AttributeError: ... 'SessionAggregator'`

- [ ] **Step 3: Write minimal implementation**

Add after `RecapContext`:

```python
@dataclasses.dataclass(frozen=True)
class Aggregation:
    text: str
    start_hhmm: str
    end_hhmm: str


class SessionAggregator:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def aggregate(self) -> Aggregation | None:
        out = run_aggregator(self._ctx.sid8, since=self._ctx.since)
        if not out:
            return None
        window = parse_session_window(out)
        if window is None:
            log("could not parse Session header from aggregator output")
            return None
        return Aggregation(text=out, start_hhmm=window[0], end_hhmm=window[1])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_note_resolver.py tests/test_auto_recap.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/garden-recap/auto_recap.py tests/test_daily_note_resolver.py
git commit -m "refactor(auto-recap): add SessionAggregator wrapping aggregate+window parse" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Introduce `DailyNoteResolver` (the clarity-critical class)

**Files:**
- Modify: `skills/garden-recap/auto_recap.py` (add class; it *calls* the existing `pre_resolve_daily_path`, `resolve_daily_path`, `compute_readme_hash`, `read_discovery_cache`, `write_discovery_cache`, `parse_discovery` functions — those stay as module functions)

`DailyNoteResolver` is a stateful wrapper around the location-resolution flow. It holds the `RecapContext`, computes/caches the readme hash and cached discovery on construction, and exposes three methods plus a `pre_resolved` flag so the orchestrator can pick the prompt template without branching on internals.

Interface:
- `pre_resolve() -> tuple[pathlib.Path, str] | None` — `(daily_path, insert_before)` via env + cache only (no LLM). Sets `self.pre_resolved`.
- `resolve_from_discovery(claude_output: str) -> tuple[pathlib.Path, str] | None` — parse LLM discovery block, resolve path, stash discovery for `persist_cache`. Returns `(daily_path, insert_before)`.
- `persist_cache() -> None` — write discovery cache if this was a miss-path run with usable values.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_daily_note_resolver.py`:

```python
def _ctx_with_vault(mod, tmp_path):
    vault = tmp_path / "vault"
    (vault / "04_DailyNotes").mkdir(parents=True)
    return mod.RecapContext(sid8="abcd1234", vault=vault, today_str="2026-05-29", since=None), vault


def test_resolver_pre_resolve_hits_via_env(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    env = {
        "KG_DAILY_FOLDER": "04_DailyNotes",
        "KG_DAILY_FILENAME": "2026-05-29.md",
    }
    r = mod.DailyNoteResolver(ctx, dict_env=env)
    pre = r.pre_resolve()
    assert pre is not None
    daily_path, insert_before = pre
    assert daily_path == vault / "04_DailyNotes" / "2026-05-29.md"
    assert r.pre_resolved is True


def test_resolver_pre_resolve_misses_without_env_or_cache(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    r = mod.DailyNoteResolver(ctx, dict_env={})
    # No README discovery cache, no env → miss.
    monkeypatch.setattr(mod, "read_discovery_cache", lambda h: None)
    assert r.pre_resolve() is None
    assert r.pre_resolved is False


def test_resolver_resolve_from_discovery(monkeypatch, tmp_path):
    mod = _load_module()
    ctx, vault = _ctx_with_vault(mod, tmp_path)
    r = mod.DailyNoteResolver(ctx, dict_env={})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_note_resolver.py -k resolver -v`
Expected: FAIL with `AttributeError: ... 'DailyNoteResolver'`

- [ ] **Step 3: Write minimal implementation**

Add after `SessionAggregator`. The class reads env from an injected dict (default `os.environ` in production) for testability, mirroring `RecapContext.from_hook`:

```python
class DailyNoteResolver:
    def __init__(self, ctx: RecapContext, dict_env: dict[str, str] | None = None) -> None:
        self._ctx = ctx
        self._env = os.environ if dict_env is None else dict_env
        self._readme_hash = compute_readme_hash(ctx.vault)
        self._cached = (
            read_discovery_cache(self._readme_hash) if self._readme_hash else None
        )
        self._discovery: dict[str, str] = {}
        self.pre_resolved = False

    def pre_resolve(self) -> tuple[pathlib.Path, str] | None:
        pre = pre_resolve_daily_path(self._ctx.vault, self._cached, self._ctx.today_str)
        self.pre_resolved = pre is not None
        return pre

    def resolve_from_discovery(self, claude_output: str) -> tuple[pathlib.Path, str] | None:
        self._discovery = parse_discovery(claude_output)
        daily_path = resolve_daily_path(self._ctx.vault, self._discovery)
        if daily_path is None:
            log("could not resolve daily-note path (no env override and no discovery from README)")
            return None
        return (daily_path, self._discovery.get("insert_before", ""))

    def persist_cache(self) -> None:
        if (
            not self.pre_resolved
            and self._readme_hash
            and self._discovery.get("folder")
            and self._discovery.get("filename_pattern")
        ):
            write_discovery_cache(self._readme_hash, self._discovery)
```

> Note: `pre_resolve_daily_path` and `resolve_daily_path` read `os.environ` directly for `KG_DAILY_*` today. The unit tests inject env via `monkeypatch.setenv` instead of the `dict_env` param for those env-driven paths — adjust the Step 1 tests to use `monkeypatch.setenv("KG_DAILY_FOLDER", ...)` rather than passing `dict_env`, since `_env` is only used for resolver-local decisions, and the underlying functions still consult `os.environ`. Keep `dict_env` wired for future migration but set the env vars via monkeypatch in tests so the existing functions see them.

- [ ] **Step 4: Fix the Step 1 tests to set env via monkeypatch**

Update `test_resolver_pre_resolve_hits_via_env` to use `monkeypatch.setenv` instead of `dict_env`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_note_resolver.py tests/test_auto_recap.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/garden-recap/auto_recap.py tests/test_daily_note_resolver.py
git commit -m "refactor(auto-recap): add DailyNoteResolver to contain location resolution" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Introduce `DailyNote` (write + version)

**Files:**
- Modify: `skills/garden-recap/auto_recap.py` (add class; calls existing `upsert_block`, `commit_and_push`, `find_repo_root`)

`DailyNote` binds a resolved `daily_path` to its write+commit operations. It resolves `repo_root` from the vault on construction.

Interface:
- `apply_block(marker_key, block, insert_before) -> bool` — delegate to `upsert_block`.
- `commit(marker_key, start_hhmm, topic) -> None` — find repo root (cached); if none, log + skip (caller still writes cursor); else `commit_and_push`.
- `has_repo` property so the orchestrator replicates the current "no repo → log, write cursor, no-op commit" branch.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_daily_note_resolver.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_note_resolver.py -k daily_note -v`
Expected: FAIL with `AttributeError: ... 'DailyNote'`

- [ ] **Step 3: Write minimal implementation**

Add after `DailyNoteResolver`:

```python
class DailyNote:
    def __init__(self, vault: pathlib.Path, daily_path: pathlib.Path) -> None:
        self._vault = vault
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_note_resolver.py tests/test_auto_recap.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/garden-recap/auto_recap.py tests/test_daily_note_resolver.py
git commit -m "refactor(auto-recap): add DailyNote for write+version operations" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire `AutoRecap` orchestrator and slim `main()`

**Files:**
- Modify: `skills/garden-recap/auto_recap.py` (add `AutoRecap` class; rewrite `main()` to delegate)

This is the integration task. `AutoRecap.run()` replicates the exact control flow of today's `main()` (lines 580–740) using the collaborators built in Tasks 1–4. `main()` becomes a thin wrapper. **No new no-op condition or behavior is added** — every `return` / `emit_continue` site in current `main()` maps to a site in `run()`.

- [ ] **Step 1: Confirm the behavior contract is green before integration**

Run: `python -m pytest tests/test_auto_recap.py -q`
Expected: all PASS (baseline before rewriting `main`).

- [ ] **Step 2: Add the `AutoRecap` class**

Add before `main()`. This mirrors `main()` step-for-step (debounce + session-log guards live here, per Task 1's ordering note):

```python
class AutoRecap:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def run(self) -> None:
        ctx = self._ctx

        # debounce
        marker = debounce_marker(ctx.sid8)
        try:
            if marker.exists():
                age = time.time() - marker.stat().st_mtime
                if age < DEBOUNCE_SECONDS:
                    return
        except OSError:
            pass

        # session log must exist and be non-empty
        log_path = session_log_path(ctx.sid8)
        if not log_path.is_file() or log_path.stat().st_size == 0:
            return

        agg = SessionAggregator(ctx).aggregate()
        if agg is None:
            return
        marker_key = f"{ctx.sid8}-{agg.start_hhmm.replace(':', '')}"

        resolver = DailyNoteResolver(ctx)
        pre = resolver.pre_resolve()

        readme, template = load_vault_context(ctx.vault)
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
            return
        prompt_template = prompt_template_path.read_text(encoding="utf-8")

        prompt = compose_prompt(
            prompt_template,
            {
                "SID8": ctx.sid8,
                "MARKER_KEY": marker_key,
                "START_HHMM": agg.start_hhmm,
                "TODAY": ctx.today_str,
                "VAULT_README": readme,
                "DAILY_TEMPLATE": template,
                "EXISTING_DAILY": existing_daily,
                "AGGREGATOR_OUTPUT": agg.text,
            },
        )

        timeout = int(os.environ.get("KG_AUTO_RECAP_TIMEOUT", str(DEFAULT_TIMEOUT)))
        out = call_claude(prompt, timeout=timeout)
        if not out:
            return

        if pre is None:
            resolved = resolver.resolve_from_discovery(out)
            if resolved is None:
                return
            daily_path, insert_before = resolved

        block = extract_block(out, marker_key)
        if not block:
            log("claude output missing recap markers")
            return

        topic = extract_topic(block)
        if topic is None:
            log(f"could not extract topic from block for {marker_key}; using fallback subject")

        note = DailyNote(ctx.vault, daily_path)
        if not note.apply_block(marker_key, block, insert_before):
            return

        if not note.has_repo:
            log("vault is not in a git repo — skipping commit; cursor still updated")
            write_cursor(ctx.sid8, agg.end_hhmm)
            return
        note.commit(marker_key, agg.start_hhmm, topic)
        write_cursor(ctx.sid8, agg.end_hhmm)

        resolver.persist_cache()

        try:
            marker = debounce_marker(ctx.sid8)
            marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker.touch()
        except OSError:
            pass
```

- [ ] **Step 3: Rewrite `main()` to delegate**

Replace the entire body of `main()` (current lines 580–740) with:

```python
def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        emit_continue()
        return

    ctx = RecapContext.from_hook(raw, os.environ)
    if ctx is None:
        emit_continue()
        return

    try:
        AutoRecap(ctx).run()
    finally:
        emit_continue()
```

> The single `emit_continue()` in the `finally` replaces the ~12 scattered `emit_continue()` calls in old `main()`. Because every old exit path called `emit_continue()` exactly once and then returned, funnelling it into `finally` is behavior-identical (the hook always emits exactly one continue payload).

- [ ] **Step 4: Delete now-dead code**

Confirm no orphaned references remain. The old inline logic in `main()` is gone. Do NOT delete the module helper functions the classes call.

Run: `python -c "import ast,sys; ast.parse(open('skills/garden-recap/auto_recap.py').read())"`
Expected: no output (parses cleanly).

- [ ] **Step 5: Run the full suite to verify behavior is preserved**

Run: `python -m pytest tests/test_auto_recap.py tests/test_daily_note_resolver.py tests/test_recap_aggregate.py -q`
Expected: ALL PASS. If any subprocess test in `test_auto_recap.py` fails, the integration diverged from current behavior — fix `run()` to match, do not edit the test.

- [ ] **Step 6: Commit**

```bash
git add skills/garden-recap/auto_recap.py
git commit -m "refactor(auto-recap): orchestrate via AutoRecap.run(), slim main()" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: pre-commit, full verification, and PR

**Files:** none (verification + integration)

- [ ] **Step 1: Run pre-commit on all changed files**

Run: `pre-commit run --files skills/garden-recap/auto_recap.py tests/test_daily_note_resolver.py docs/specs/2026-05-29-auto-recap-class-refactor-design.md docs/superpowers/plans/2026-05-29-auto-recap-class-refactor.md`
Expected: all hooks Pass. Fix any reported issues (do not `--no-verify`).

- [ ] **Step 2: Run the entire test suite one final time**

Run: `python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 3: Eyeball the legibility win**

Open `skills/garden-recap/auto_recap.py` and confirm `AutoRecap.run()` reads as a linear outline and the location-resolution branching is no longer visible in `run()` (it's inside `DailyNoteResolver`). This is the goal of the refactor — confirm it visually.

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin refactor/auto-recap-classes
gh pr create --title "refactor(auto-recap): split main() into role classes" --body "$(cat <<'EOF'
## Summary
Behavior-preserving refactor of `skills/garden-recap/auto_recap.py`. Splits the monolithic `main()` into role-focused classes (`RecapContext`, `SessionAggregator`, `DailyNoteResolver`, `DailyNote`, `AutoRecap`) so the Stop-hook pipeline reads as an outline. Groundwork for #18.

## Behavior
No external behavior change. The 30+ subprocess tests in `tests/test_auto_recap.py` are unchanged and green. Added unit tests for the location-resolution logic (`tests/test_daily_note_resolver.py`).

## Out of scope
- Substance gate (#18 A) — slots into `SessionAggregator` next.
- Coalesce redesign (#18 B).

Spec: `docs/specs/2026-05-29-auto-recap-class-refactor-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** Tasks 1–5 implement the 5 classes and the orchestrator from the spec's component table; Task 5 preserves the data flow; error-handling contract preserved (single `emit_continue` in `finally`, methods return None/False); testing strategy = unchanged subprocess suite (Task 5 Step 5) + new `DailyNoteResolver`/class unit tests (Tasks 1–4). Non-goals (substance gate, coalesce) explicitly excluded.
- **Ordering caveat documented:** debounce / session-log guards move from mid-`main()` into `AutoRecap.run()` head; justified as side-effect-safe and outcome-equivalent (Task 1 note).
- **env injection caveat documented:** `dict_env` is wired for `KG_AUTO_RECAP`/`KG_VAULT` gating (RecapContext) but the `KG_DAILY_*` overrides are still read from `os.environ` by the underlying `*_daily_path` functions; tests set those via `monkeypatch.setenv` (Task 3 Step 4).
- **Type consistency:** `Aggregation(text, start_hhmm, end_hhmm)`, `RecapContext(sid8, vault, today_str, since)`, `DailyNoteResolver(ctx, dict_env=None)` with `.pre_resolve()/.resolve_from_discovery()/.persist_cache()/.pre_resolved`, `DailyNote(vault, daily_path)` with `.apply_block()/.commit()/.has_repo` — used consistently across tasks.
