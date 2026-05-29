# Recap Package Restructure — Design

- **Date**: 2026-05-29
- **Status**: Draft
- **Type**: Refactor (behavior-preserving directory move)
- **Prior art**: [2026-05-29-auto-recap-class-refactor-design.md](2026-05-29-auto-recap-class-refactor-design.md)

## Problem

`skills/garden-recap/` mixes **skill content** (`SKILL.md` + prompt templates) with a **hook-driven Python subsystem** (10 files: `capture.py`, `auto_recap.py`, `recap_aggregate.py`, the five split modules, plus prompt templates). Every other skill directory holds only `SKILL.md`, so `garden-recap` is asymmetric.

The recap subsystem is driven by `PostToolUse` and `Stop` **hooks**, not by a skill's own instructions. Researched references (the official Anthropic plugin/skill spec, `obra/superpowers`, `thedotmack/claude-mem`) uniformly separate the hook-driven **program** from **skill content**: the official convention puts hook scripts in a plugin-level location referenced via `${CLAUDE_PLUGIN_ROOT}`, while `skills/<name>/scripts/` bundles are reserved for skill-instruction-driven helpers. The current layout is the reverse.

## Goal

Move the recap engine into a dedicated top-level `recap/` package so that `skills/` holds only skill content, with **zero behavior change**.

## Target structure

```
recap/                          # NEW: the hook-driven recap engine
  capture.py                    # PostToolUse hook entry
  auto_recap.py                 # Stop hook entry + AutoRecap orchestrator
  recap_aggregate.py            # aggregator (subprocess + CLI)
  recap_common.py
  recap_context.py
  session_aggregator.py
  daily_note_resolver.py
  daily_note.py
  kg_paths.py                   # moved from lib/ (recap is its only consumer)
  prompts/
    auto_recap_prompt.md
    auto_recap_compose_prompt.md
skills/
  garden-recap/SKILL.md         # code removed; SKILL.md only (symmetric with other skills)
  garden-{plant,survey,water,prune,connect}/SKILL.md
  using-knowledge-gardener/SKILL.md
hooks/{hooks.json, session-start}
scripts/{bump-version.sh, check-*.sh}   # repo tooling, unchanged
tests/                          # flat, path constants updated only
docs/                           # unchanged
```

## Decisions

- **Drop `lib/`**: `kg_paths.py` is imported only by recap scripts (`capture.py`, `recap_common.py`, `recap_aggregate.py`, and `test_recap_aggregate.py`). Move it to `recap/kg_paths.py` and delete `lib/`.
- **Simplify `sys.path`**: with every module in `recap/`, each module's existing `sys.path.insert(0, <own dir>)` makes `from kg_paths import …` resolve directly. Remove the now-obsolete `parents[2] / "lib"` insert from `recap_common.py`, `capture.py`, and `recap_aggregate.py`.
- **Fix `plugin_root()`**: defined in `recap_common.py`. Moving from `skills/garden-recap/` to `recap/` changes the repo-root depth from `parents[2]` to `parents[1]`.
- **Update path construction** to the new locations:
  - `hooks/hooks.json`: `${CLAUDE_PLUGIN_ROOT}/recap/capture.py` and `…/recap/auto_recap.py`.
  - `auto_recap.py`: prompt template path → `plugin_root() / "recap" / "prompts" / "auto_recap_{,compose_}prompt.md"`.
  - `session_aggregator.py`: aggregator path → `plugin_root() / "recap" / "recap_aggregate.py"`.
  - `skills/garden-recap/SKILL.md`: the `recap_aggregate.py` invocation example → `${CLAUDE_PLUGIN_ROOT}/recap/recap_aggregate.py`.
- **Prompts** move into `recap/prompts/`.
- **Docs**: update `skills/garden-recap/…` path references in `CLAUDE.md`, `README.md`, `SKILL.md`, and the moved `kg_paths.py` docstring (and the in-file comments in `recap_aggregate.py` / `recap_common.py` / `capture.py`) to `recap/…`.

## Out of scope

- Consolidating `docs/{plans,specs,superpowers/plans}` — separate, minor.
- Reorganizing `tests/` into subdirectories — separate, minor.
- Any change to the other skills (`garden-plant` etc.) or to behavior.

## Verification

Behavior is unchanged. The subprocess contract tests (`tests/test_auto_recap.py`, `tests/test_capture.py`, `tests/test_recap_aggregate.py`) are the safety net; **only their path constants** (the `… / "skills" / "garden-recap" / …` literals that locate the moved files) are updated — assertions are untouched. `tests/test_daily_note_resolver.py`'s `GARDEN` sys.path dir updates from `skills/garden-recap` to `recap`. Full suite (81 tests) must stay green; `pre-commit run --files <all changed>` must pass.
