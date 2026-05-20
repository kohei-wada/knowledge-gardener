# Recap Aggregator (Phase 2) — Design

- **Date**: 2026-05-20
- **Status**: Approved
- **Target release**: knowledge-gardener v0.9.0
- **Source RFP**: [GitHub issue #1](https://github.com/Kohei-Wada/knowledge-gardener/issues/1)
- **Phase**: 2 of 3 (consumer; Phase 1 capture shipped in v0.8.0)
- **Prior art**: [2026-05-18-session-capture-design.md](2026-05-18-session-capture-design.md) (Phase 1 writer)

## Goal

Replace `garden-recap`'s recollection-based session inventory (Step 3 of the existing skill) with a deterministic aggregation of the session log written by Phase 1. The skill still proposes-and-confirms before writing to the daily note — what changes is the **evidence source**, not the user-facing flow.

## Why split from Phase 1

Phase 1 ships the capture hook with zero behavior change in `garden-recap`. This phase opt-in upgrades the consumer side. Splitting lets us soak the capture format in real sessions (we expect the log to drift; Phase 1 logs from the day after release inform any format tweaks Phase 2 needs).

## Scope (v0.9.0)

### In scope

- New `scripts/recap_aggregate.py` (stdlib only) — discovers today's session logs, emits a structured plain-text summary that `garden-recap` quotes into its proposal.
- `skills/garden-recap/SKILL.md` Step 3 gains a precursor: invoke the aggregator first; use its output as evidence; **only** fall back to recollection if the aggregator returns no captures or fails.
- Tests for the aggregator under `tests/test_recap_aggregate.py`.

### Out of scope (Phase 3 / future)

- Stop hook to auto-fire `garden-recap` — separate spec, future release.
- Cross-session merging (e.g. weekly digests) — separate skill.
- Log retention / GC — separate `garden-prune-sessions` skill (still future).
- AI compression of the aggregator output — keep deterministic plain text; the skill is responsible for distilling bullets.

## Log → aggregate transformation

### Input

`$XDG_STATE_HOME/knowledge-gardener/sessions/<YYYY-MM-DD>-<sid8>.log` lines, format defined in Phase 1:

```
HH:MM tool=<Tool> target=<one-line> [status=ok|err]
```

### Output (plain text, sectioned)

```
# Sessions on <YYYY-MM-DD>
<N> session(s) found.

## Session <HH:MM> - <HH:MM> (sid8: <sid8>)
Duration: <total-minutes>m, <total-entries> captured tool calls.

### Files touched
- <relative-path-or-short-path> (<n> edits)
- ...

### Bash highlights
- <command-truncated-to-80>
- ...

### Other tool activity
- Agent: <n> dispatch(es) — <subagent_types>
- WebFetch/WebSearch: <n>
- MCP: <server>(<n>), <server>(<n>)
- Errors: <n>

```

Each session block is independently quotable. The skill picks one (most recently modified, by default) or asks the user when multiple sessions exist for the same day.

### Field-level rules

- **Duration**: `last_entry.HH:MM − first_entry.HH:MM`, rounded to whole minutes. If the entry list crosses midnight the script will still compute a non-negative value (mod 24h) — multi-day sessions are edge cases and Phase 1's "log splits at midnight" invariant means in practice this isn't reached.
- **Files touched**: dedup by target string. `<n> edits` counts the number of log lines for that target. Edit + Write + NotebookEdit are merged (treated equivalently).
- **Bash highlights**: dedup exact-duplicate targets; preserve order of first occurrence. Cap at 10 lines per session to keep output bounded.
- **Other tool activity**: counts per category. Subagent types are listed unique. MCP servers are counted per-server (slack count + notion count etc.).
- **Errors**: count of entries with `[status=err]`.

### Empty log

A session log file that exists but contains no parseable entries still produces a session block with `0 captured tool calls` and the rest left empty. This means "the session started and Phase 1 was active but nothing material happened" — useful evidence in itself.

## CLI surface

```
scripts/recap_aggregate.py [--date YYYY-MM-DD] [--sid <sid8>] [--all]
```

- No flags: emit today's most-recently-modified session log only (likely the active session).
- `--date <YYYY-MM-DD>`: aggregate sessions for that date instead of today.
- `--sid <sid8>`: aggregate only that session (skill uses this when user picks).
- `--all`: include every session for the chosen date instead of just the latest.

`--sid` and `--all` are mutually exclusive; later one wins if both passed (no hard error — best-effort).

If the log dir is missing entirely the script prints `# Sessions on <date>\n0 session(s) found.` and exits 0. No FS errors raised — this is read-only consumption and we'd rather degrade than crash the skill.

## Skill integration

`skills/garden-recap/SKILL.md` Step 3 (inventory) is rewritten to be aggregator-first:

```
3a. Run scripts/recap_aggregate.py (via the plugin's CLAUDE_PLUGIN_ROOT) for today's logs.
3b. If the aggregator output contains at least one session block: use that as the
    evidence inventory for outcomes / files / agents. Cross-check with `git log`
    for vault changes today.
3c. If the aggregator returns "0 session(s) found": fall back to the existing
    recollection-based inventory. (No log, no upgrade — preserve previous UX.)
3d. Either way: open follow-ups and learnings still come from conversation
    context, since the log records actions, not reasoning.
```

The skill body changes; the proposal/confirmation flow does not.

## File layout (delta)

| Path | Action | Notes |
|------|--------|-------|
| `scripts/recap_aggregate.py` | Create | Python 3 stdlib only |
| `tests/test_recap_aggregate.py` | Create | pytest cases via `uv run --with pytest` |
| `skills/garden-recap/SKILL.md` | Modify | Rewrite Step 3 inventory section per above |
| `README.md` | Modify | Update "Session Capture" section to note Phase 2 |
| `CLAUDE.md` | Modify | Note the consumer side under the existing hook bullet |
| `docs/specs/2026-05-18-session-capture-design.md` | Modify | Mark Phase 2 hand-off notes as "implemented" |
| `package.json` / `plugin.json` / `marketplace.json` | Bump | `0.8.0` → `0.9.0` |

## Robustness

- Log file unreadable mid-aggregation: skip that file, aggregate the rest.
- Malformed log line (does not match `HH:MM tool=...` shape): skip, count under "unparsed" but do not include in the human output. The hook is supposed to produce well-formed lines; this guards against future format drift.
- `XDG_STATE_HOME` set to a non-directory: same as "no log dir" — return zero-session output.

## Edge cases

- **Two sessions with the same sid8 on the same day**: cannot happen — Phase 1's `<sid8>` is derived from `session_id` which is unique per Claude Code session. If it does happen (clock skew, transcript-replay), they coexist in the same file because the filename matches; the aggregator treats them as one session, which is acceptable.
- **No tools captured but log file exists** (e.g. session consisted only of `Read` and `TodoWrite`): aggregator emits the session block with all counts at 0. The skill still records "this session existed" — useful when the user wants to note a planning-only session.
- **Garden-recap invoked from a project that is not the vault repo**: aggregator doesn't care; it reads `~/.local/state/...`, not the vault. The skill's Step 3d (git log for vault changes) is the part that needs the vault path, and that uses `$KG_VAULT` as it does today.

## Release Checklist (v0.9.0)

1. New `scripts/recap_aggregate.py` per this design.
2. New `tests/test_recap_aggregate.py` covering: single-session, multi-session, `--sid` selection, `--all`, missing log dir, malformed lines, files dedup, error counting.
3. Update `skills/garden-recap/SKILL.md` Step 3 to be aggregator-first.
4. Update `README.md` and `CLAUDE.md` to note Phase 2 ships.
5. Mark Phase 2 hand-off notes in `2026-05-18-session-capture-design.md` as implemented (do not delete — historical context).
6. Bump `package.json` / `.claude-plugin/plugin.json` / `.claude-plugin/marketplace.json` to `0.9.0` atomically.
7. Commit, tag `v0.9.0`, push.
