# auto_recap.py Class Refactor — Design

- **Date**: 2026-05-29
- **Status**: Implemented
- **Type**: Refactor (behavior-preserving)
- **Prior art**: [2026-05-20-auto-recap-design.md](2026-05-20-auto-recap-design.md), [2026-05-21-per-stop-recap-blocks-design.md](2026-05-21-per-stop-recap-blocks-design.md)
- **Related issue**: [#18](https://github.com/Kohei-Wada/knowledge-gardener/issues/18) (this refactor is the groundwork; the substance gate "A" and coalesce "B" are out of scope here)

## Problem

`skills/garden-recap/auto_recap.py` has grown to ~748 lines. All orchestration lives in a single procedural `main()` that threads `sid8` / `vault` / `marker_key` / `since` through a long linear flow with two interleaved branches (pre-resolve path vs. LLM-discovery path) for resolving the daily-note location. The structure has become hard to follow — you cannot see the end-to-end flow without reading the whole function, and the daily-note-location logic (discovery cache, README hashing, env overrides, pre-resolve, LLM-discovery parsing) is the densest, most tangled sub-area.

This is **not** a functional bug. The goal is legibility: make the Stop-hook pipeline readable at a glance and isolate the confusing location-resolution logic behind a clear boundary.

## Goal

Split `auto_recap.py` into role-focused classes so that:

1. The orchestration (`AutoRecap.run()`) reads as an outline of the pipeline.
2. The daily-note-location branching is fully contained in one class (`DailyNoteResolver`).
3. External behavior is **identical** — verified by the existing subprocess test suite staying green.

## Non-goals

- **No** substance gate (issue #18 direction A). It slots into `SessionAggregator.aggregate()` afterward.
- **No** coalesce redesign (issue #18 direction B).
- **No** change to the prompt templates, the discovery-cache format, env-var contract, marker format, or commit-subject shape.
- **No** rewrite of the pure helper functions that are already well-tested.

## Addendum (post-implementation): file split

This design originally kept all classes in the single `auto_recap.py` module. After the class refactor landed, the file was split into focused sibling modules (still behavior-preserving, subprocess suite unchanged and green):

- `recap_common.py` — shared primitives (logging, constants, `kg_paths` wrappers, `plugin_root`, `read_text`, cursor I/O).
- `recap_context.py` — `RecapContext`.
- `session_aggregator.py` — `Aggregation`, `SessionAggregator`, `run_aggregator`, `parse_session_window`.
- `daily_note_resolver.py` — `DailyNoteResolver` + discovery-cache and path-resolution helpers.
- `daily_note.py` — `DailyNote` + block/upsert/git helpers.
- `auto_recap.py` — slim entry: `load_vault_context`, `compose_prompt`, `call_claude`, `AutoRecap`, `main`.

Each module self-bootstraps its own dir onto `sys.path` so sibling imports resolve both when the hook runs as a script and when the unit tests import the modules. Dead symbols (`vault_root`, `daily_note_path`, `MARKER_OPEN_RE`, unused `kg_state_dir` import) were dropped along the way.

## Architecture

```
                         ┌──────────────────────────────┐
   stdin(JSON) ─────────►│  AutoRecap  (orchestrator)    │
   env (KG_*)            │  run() = readable pipeline     │
                         └──────────────────────────────┘
                            │      │        │         │
              ┌─────────────┘      │        │         └──────────────┐
              ▼                    ▼        ▼                        ▼
     ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐
     │ RecapContext   │  │ SessionAggregator│  │ DailyNoteResolver │  │ DailyNote    │
     │ (immutable)    │  │ "what happened"  │  │ "where to write"  │  │ "write+commit"│
     └────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────┘
```

### Components

| Class | Responsibility | Migrated from |
|-------|----------------|---------------|
| `RecapContext` | Immutable per-invocation facts: `sid8`, `vault`, `today_str`, `since`. Built once from the hook payload + env. | `main()` preamble (stdin parse, env gate, `vault_root`, `read_cursor`) |
| `SessionAggregator` | Run the aggregator and parse the session window. Returns an `Aggregation(text, start_hhmm, end_hhmm)` or `None` (no-op). | `run_aggregator`, `parse_session_window`, the L229–234 no-op string checks |
| `DailyNoteResolver` | Resolve **where** to write, containing both branches. `pre_resolve()` (env + cache, no LLM) → `(daily_path, insert_before)` or `None`; `resolve_from_discovery(out)` (parse LLM discovery block, resolve path); `persist_cache()`. Exposes whether pre-resolve hit so the orchestrator picks the prompt template. | `compute_readme_hash`, `_read_readme_bytes`, `read_discovery_cache`, `write_discovery_cache`, `discovery_cache_path`, `substitute_date`, `pre_resolve_daily_path`, `resolve_daily_path`, `_validate_daily_path`, `parse_discovery`, `_resolve_under_vault` |
| `DailyNote` | Given a resolved `daily_path`: `apply_block(marker_key, block, insert_before) -> bool` (upsert, returns whether the file changed); `commit(marker_key, start_hhmm, topic)` (pre-commit → add → commit → push). Holds `repo_root`. | `upsert_block`, `commit_and_push`, `find_repo_root`, `build_commit_subject` |
| `AutoRecap` | Orchestrator. `run()` calls the above in order with early-return no-ops. | `main()` |

### Kept as module-level functions

These are pure / already-tested and gain nothing from being methods; the orchestrator and classes call them directly:

`emit_continue`, `log`, `call_claude`, `compose_prompt`, `build_prompt` (template selection), `load_vault_context`, `read_text`, `extract_block`, `extract_topic`, all regexes, `read_cursor` / `write_cursor`, `debounce_marker` / `cursor_path` / `session_log_path` wrappers, `plugin_root`, `vault_root`.

## Data flow (`AutoRecap.run()`)

```
1.  ctx = RecapContext.from_hook(stdin, env)      → None ⇒ emit_continue (env unset / bad payload / no vault)
2.  debounce: marker mtime < DEBOUNCE_SECONDS     → no-op
3.  session log exists & non-empty?               → no-op if not
4.  agg = SessionAggregator(ctx).aggregate()      → None (0 calls / --:-- window) ⇒ no-op
        marker_key = f"{ctx.sid8}-{agg.start_hhmm without ':'}"
5.  resolver = DailyNoteResolver(ctx)
    pre = resolver.pre_resolve()                  → hit: daily_path fixed, compose-only template
                                                    miss: discovery template, path resolved post-LLM
6.  prompt = build_prompt(template, substitutions)
7.  out = call_claude(prompt, timeout)            → None ⇒ no-op
8.  daily_path = pre.daily_path  OR  resolver.resolve_from_discovery(out)   → None ⇒ no-op
9.  block = extract_block(out, marker_key)         → None ⇒ no-op
    topic = extract_topic(block)
10. note = DailyNote(ctx, daily_path)
    changed = note.apply_block(marker_key, block, insert_before)  → False ⇒ no-op
11. note.commit(marker_key, agg.start_hhmm, topic)
    write_cursor(ctx.sid8, agg.end_hhmm)
    resolver.persist_cache()                       # only on a pre-resolve miss with usable discovery
    touch debounce marker
12. emit_continue
```

Every step preserves the current "failure or empty → log + emit_continue" early-return shape one-for-one.

## Error handling (unchanged contract)

- Fire-and-forget is preserved: every failure path calls `log()` then `emit_continue()`. The hook must never block Claude.
- Class methods **do not raise** for expected failure modes — they return `None` / `False`, and the orchestrator translates that to a no-op. This mirrors the existing `return`-to-exit flow.
- The `__main__` top-level `try/except → log("uncaught: ...") + emit_continue` stays.
- Env-override precedence, corrupted-cache fallback, and the directory-tree-root hint log all keep their current behavior.

## Testing

- **`tests/test_auto_recap.py` (subprocess, 30+ cases) stays unchanged and green.** It exercises the hook at the process boundary, so a green run is the behavior-preserving guarantee.
- **Add unit tests for `DailyNoteResolver`** — the logic-dense class that motivated the refactor. Import it directly and cover: env-override wins, cache hit, cache miss → discovery, corrupted cache fallback, suspicious-path rejection, vault-basename hint. Plain-stdlib style matching `tests/test_recap_aggregate.py`.
- No new unit tests for the other classes; the subprocess suite already covers them (YAGNI).

## Future fit (informational, not in scope)

- **Substance gate (#18 A)**: add `has_substance` to `SessionAggregator`; `aggregate()` returns `None` when no durable change (file edit / Agent dispatch / git commit-push) is present.
- **Coalesce (#18 B)**: expected to be contained largely within `DailyNote` (block upsert strategy) and `RecapContext` (session-keying), validating the boundaries chosen here.
