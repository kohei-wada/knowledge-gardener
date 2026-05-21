# Per-Stop Recap Blocks — Design

- **Date**: 2026-05-21
- **Status**: Draft
- **Target release**: knowledge-gardener v0.13.0
- **Prior art**: [2026-05-20-auto-recap-design.md](2026-05-20-auto-recap-design.md), [2026-05-20-recap-aggregator-design.md](2026-05-20-recap-aggregator-design.md)

## Problem

Today's `auto_recap.py` keys each daily-note block by `sid8` and **replaces** the prior block on every subsequent Stop event in the same session. The aggregator already reads the full append-only session log, so the underlying data is preserved — but the rendered block (including the KPT that Claude composed last round) gets overwritten. Any nuance the user picked up after the previous Stop is lost.

Symptom in the wild: `04_DailyNotes/2026-05-21.md` contains a block keyed `kg-recap-sid:279c00ff` and a second block keyed `kg-recap-sid:279c00ff-2` — a manual workaround to keep both halves of a long session.

User intent: **the chronological trail of work should accumulate; nothing previously written should be discarded just because the session continued.**

## Goal

Each Stop event produces its own block, scoped to the interval since the previous Stop in that session. Old blocks are never touched. The day's daily note ends up with a disjoint, time-ordered list of session blocks.

## Scope (v0.13.0)

### In scope

- New marker format `<!-- kg-recap-sid:{sid8}-{HHMM} -->` (HHMM = block start, the first activity timestamp the block summarises).
- `auto_recap.py`:
  - Drop the "find-and-replace by sid8" branch. New blocks are always inserted.
  - Track the "last recapped HHMM" per `sid8` in a cursor file under `$XDG_STATE_HOME/knowledge-gardener/sessions/{sid8}.cursor`.
  - Pass `--since HHMM` to the aggregator when a cursor exists; otherwise no filter (first block covers from session start).
  - After a successful write, update the cursor to the latest log line's HHMM (or the wall-clock now if the log somehow has no later line).
- `recap_aggregate.py`:
  - New `--since HHMM` flag. Filter parsed entries to those with `hhmm >= since`.
  - Session header reports the windowed range (`Session HH:MM - HH:MM`) computed from the filtered entries, not the whole log.
  - If filtering yields zero entries: emit `0 session(s) found` so `auto_recap.py` treats it as a no-op.
- Idempotency on retry: if a marker `kg-recap-sid:{sid8}-{HHMM}` already exists, replace that exact block (covers the case where pre-commit fails and the hook reruns within debounce window). Different HHMM = different block, never collides.
- Auto-recap prompt template (`auto_recap_prompt.md`): update the marker placeholder to the new `{sid8}-{HHMM}` form and instruct Claude to use the windowed range for the `Session HH:MM 〜` heading.
- Tests:
  - Aggregator `--since` filtering (entries before / on / after the cutoff).
  - `auto_recap.py` cursor read/write across two Stop events (mocked Claude, mocked session log).
  - `upsert_block` no longer drops prior `sid8-HHMM` blocks when a different HHMM arrives.

### Out of scope

- Migration of existing `kg-recap-sid:{sid8}` blocks already in users' daily notes. They are left as historical artifacts; the new behaviour kicks in for new Stop events only.
- A `garden-recap` (manual skill) parallel change. The skill is interactive — the user can see and edit the proposed block. Keep it as-is in v0.13.0; a follow-up can align it.
- Cross-midnight handling. The existing `_dt.date.today()` resolution already partitions logs and notes by local date; that's an independent concern.
- Compaction / coalescing of many small blocks. Users who Stop frequently will get many blocks per day. If this proves noisy in practice, a later release can offer an off-by-default merge step.

## Design

### Time formats and naming

To avoid confusion this spec uses two distinct names:

- **`HHMM`** — colon-stripped string like `0957`. Used in the marker suffix only.
- **`HH:MM`** — colon-bearing string like `09:57`. Used everywhere else: log lines (existing format), cursor file content, `--since` CLI argument, and the human-readable `Session HH:MM 〜` heading inside the block.

`HHMM` exists solely because the marker regex in `auto_recap.py` (`[A-Za-z0-9_-]+`) does not accept `:`. We strip the colon at the marker boundary; everywhere else we keep it.

### Marker format

```
<!-- kg-recap-sid:{sid8}-{HHMM} -->
... block body ...
<!-- /kg-recap-sid:{sid8}-{HHMM} -->
```

- `sid8`: unchanged — first 8 chars of the Claude session id.
- `HHMM`: the **start** time of this block's window (e.g. `0957` for a block covering 09:57 onwards). Picking the start (not the end) keeps the marker stable across retries within the debounce window — the start time is determined by the filtered log and the cursor, both of which are stable.
- Existing marker regex `[A-Za-z0-9_-]+` accepts the new form without modification.

### Cursor file

Path: `$XDG_STATE_HOME/knowledge-gardener/sessions/{sid8}.cursor` (alongside the existing session log and debounce marker, all under `sessions/`).

Content: a single line in `HH:MM` form (with the colon — matches log entries directly), the timestamp of the **last entry included in the most recent successfully-written block**. No JSON, no header — keep it diff-friendly and trivial to read in shell.

The next Stop firing reads this `HH:MM` and passes it as `--since` to the aggregator. The aggregator includes only entries whose `hhmm > since` (strict greater-than, so the previous block's last entry is not re-summarised).

Lifecycle:
- Read at the start of each Stop hook firing (after debounce check).
- Written only after `upsert_block` returns `changed=True` AND the git commit succeeded (or, when not in a git repo, after the write succeeded).
- Not written if the aggregator returned no new entries (no-op path).
- Never deleted by the plugin. Stale cursors linger harmlessly; their `sid8` will not be reused.

### Aggregator filtering

`recap_aggregate.py --since HH:MM`:

- Argument format: `HH:MM` (with colon) — matches the log's own timestamp format and the cursor file. Validation: reject anything not matching `^\d{2}:\d{2}$`.
- Parse the log as today.
- Drop entries whose `hhmm <= since` (strict greater-than — the previous block's last entry must not appear in the next block).
- Compute the session header's start/end from the filtered list.
- If the filtered list is empty, emit `0 session(s) found` and exit 0 — `auto_recap.py` treats this as a no-op.
- All other formatting (Files touched / Bash highlights / etc.) is unchanged but operates on the filtered list.

When `--since` is unset, behaviour is identical to today.

### Hook orchestration

```
1. Read hook payload, get sid8. (unchanged)
2. KG_AUTO_RECAP gate. (unchanged)
3. Debounce check via sid8-keyed marker. (unchanged; protects against double-fire within 60s.)
4. Resolve KG_VAULT. (unchanged)
5. Ensure session log exists and is non-empty. (unchanged)
6. NEW: read cursor file; if present, capture last_hhmm; else None.
7. Run aggregator with `--sid sid8` and `--since last_hhmm` if cursor present.
   If aggregator output is empty/none → no-op.
8. Compose prompt with current HHMM as both the block's start-time placeholder
   and the marker suffix. Call headless Claude. (mostly unchanged; new substitution.)
9. Parse Claude's discovery block. (unchanged)
10. Resolve daily-note path. (unchanged)
11. Extract the block bounded by markers using sid8-HHMM. (regex extended to
    include the HHMM suffix.)
12. upsert_block: if a block with exactly this sid8-HHMM marker exists, replace;
    else insert (anchored by discovery's insert_before or EOF). Importantly,
    a block keyed by a different HHMM under the same sid8 is left untouched.
13. On successful write + commit: update cursor to the latest filtered entry's HHMM.
14. Update debounce marker. (unchanged)
```

### Marker suffix choice

Use the `HH:MM` of the **first entry returned by the filtered aggregation** (i.e. the chronologically earliest entry in the window) as the block's marker suffix, after stripping the colon to `HHMM`. The empty-list case never reaches this step — it short-circuits as a no-op above.

This makes the marker line up exactly with the `Session HH:MM 〜` heading the existing prompt asks Claude to emit, so a reader can match marker to heading at a glance.

### Edge cases

- **First Stop in a fresh session, no cursor**: `--since` omitted, aggregator returns the full log, block covers everything from session start. Marker = first log entry's HHMM. Cursor written after success.
- **Repeated Stop within debounce window (60s)**: debounce skips the hook. No new block, no cursor update.
- **Stop fires but no new tool calls since last cursor**: aggregator returns empty, hook no-ops, cursor unchanged. Next Stop with activity will pick up correctly.
- **Pre-commit fails after the block is written to the file**: the file write succeeded but the commit didn't. On the next Stop hook firing, the cursor was NOT updated (we update only after commit success), so the aggregator will re-summarise the same interval. The block already in the file matches the new marker exactly → `upsert_block` finds the same `sid8-HHMM` and replaces it idempotently. Net: retry-safe.
- **Two Stops one minute apart with new tool activity in between**: cursor advances after the first; second block's `--since` filters out the first interval's entries. New marker has a different HHMM → both blocks coexist.
- **Clock change / log line out of order**: aggregator already tolerates this (lines are parsed but not sorted by hhmm — they're treated in file order). Filtering by `hhmm >= since` may drop entries if the clock jumped back, but that's an existing edge case, out of scope to fix here.
- **Existing `sid8`-only blocks in past daily notes**: untouched. The new regex matching `{sid8}-{HHMM}` does not collide with the bare `{sid8}` form.

### Backward compatibility

- Past daily notes are not migrated.
- The `garden-recap` skill (manual flow) continues to use whatever marker it currently emits. If it never emitted markers, no change. If it emitted bare `sid8` markers, the auto-recap hook will not collide with them (different suffix).
- `KG_AUTO_RECAP` opt-in unchanged. Users who never enabled it see no behaviour change.

## Testing

- Unit: aggregator `--since` filtering — entries strictly before / equal / after.
- Unit: aggregator header `Session HH:MM - HH:MM` reflects the filtered window.
- Unit: `auto_recap.upsert_block` — inserting a new `sid8-HHMM` block leaves an existing `sid8-HHMM'` block intact when HHMM ≠ HHMM'.
- Unit: cursor read returns `None` when file absent; round-trip write+read returns the value.
- Integration (mocked claude + mocked log): two consecutive Stop events on the same session — second block is appended with a later HHMM, first block unchanged, cursor advanced.
- Integration: retry after pre-commit failure — block replaced in place under same `sid8-HHMM`.

## Rollout

- One feature branch, one spec PR (this doc), one plan PR, one implementation PR.
- Version bump: 0.12.2 → 0.13.0 (new behaviour, not a fix).
- Release notes call out: prior session blocks no longer overwritten; users with the env var set get longer (more granular) daily notes.

## Open questions

None at draft time. Update if review surfaces any.
