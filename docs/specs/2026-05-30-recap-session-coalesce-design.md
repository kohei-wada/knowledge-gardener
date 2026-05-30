# Recap Session Coalesce — Design

- **Date**: 2026-05-30
- **Status**: Draft
- **Target release**: knowledge-gardener v0.16.0
- **Issue**: [#18](https://github.com/Kohei-Wada/knowledge-gardener/issues/18) — auto-recap floods daily notes with contentless blocks
- **Prior art**: [2026-05-21-per-stop-recap-blocks-design.md](2026-05-21-per-stop-recap-blocks-design.md), [2026-05-20-recap-aggregator-design.md](2026-05-20-recap-aggregator-design.md), [2026-05-20-auto-recap-design.md](2026-05-20-auto-recap-design.md)

## Problem

`KG_AUTO_RECAP=1` fires the `Stop` hook many times within one logical work session. Since v0.13.0 (per-stop blocks, [#12](https://github.com/Kohei-Wada/knowledge-gardener/issues/12)) **each Stop appends a new `sid8-HHMM` block** to today's daily note. Two failure modes result:

1. **Fragmentation.** One continuous effort is split across many blocks (observed: a single ansible-deploy session became 7+ blocks at 10:14 / 10:15 / 10:20 / 10:22 / 10:47 / 10:50 / 10:53).
2. **Contentless flood.** The only no-op gate is "0 captured tool calls". Any session with ≥1 captured call gets a full `Keep / Problem / Try` block, so micro-sessions (a couple of git commands, a stray MCP read) produce near-identical boilerplate KPT. Measured: up to **76 recap blocks / 1655 lines in a single daily note** (2026-05-25). Real signal is buried.

### The underlying tradeoff

The two prior designs sit at opposite ends of one axis:

| Version | Block model | Failure |
|---------|-------------|---------|
| ≤ v0.12 | one block per `sid8`, **replaced** each Stop | chronological trail lost — earlier KPT overwritten |
| v0.13.0 | one block per `sid8-HHMM`, **appended** each Stop | fragmentation + contentless flood (this issue) |

v0.13.0's own spec predicted this: *"Compaction / coalescing of many small blocks … If this proves noisy in practice, a later release can offer a merge step."* It did. This spec is that merge step, and it resolves the tradeoff rather than picking a side.

## Goal

One session = **one block**, keyed by `sid8`. The block has two layers:

- **`### Timeline`** — append-only, machine-generated, no LLM. The chronological trail. *Structurally cannot be lost* (we only ever append), which permanently closes the ≤v0.12 regression.
- **`### KPT`** — LLM-regenerated each substantive Stop from the conversation transcript. A *derived view*; overwriting it never destroys information because the Timeline (and the raw transcript + session log) remain.

Contentless micro-sessions append at most a Timeline line and **never invoke the LLM**, killing the flood.

## Stage allocation

The recap subsystem has three stages. This design touches two; `capture` is untouched.

### `recap/capture/` — **unchanged**
Already appends `HH:MM tool=X target=Y [status=ok]` per material tool call, with trivial tools (`Read`, `Skill`, `ls`/`cat`/`grep`, …) pre-filtered. This is sufficient raw material for the mechanical Timeline, and KPT reads the transcript directly — so capture needs no awareness of conversation content. Append-only source of truth; leave it.

### `recap/aggregate/` — **add Timeline render + substance signal**
- **New chronological Timeline output.** Today's render groups by category (`### Files touched`, `### Bash highlights`). Add a time-ordered projection of the windowed slice suitable for direct insertion as Timeline bullets (one bullet per minute-bucket or per entry; see "Timeline rendering").
- **Expose a substance flag.** The aggregator already computes `file_counts`, `agent_count`, `bash_highlights`, `entry_count`, `duration_min`. Surface a machine-readable `durable_change: yes|no` and the counts so the recap stage can gate without re-parsing. (`durable_change` = any Edit/Write, any `git commit`/`git push` in bash highlights, or any Agent dispatch.)
- `--since HH:MM` windowing is **reused unchanged**.

### `recap/autorecap/` — **the bulk of the change**
1. **Marker** `kg-recap-sid:{sid8}-{HHMM}` → `kg-recap-sid:{sid8}` (drop the suffix; one block per session).
2. **Two-layer block model** in `daily_note.py`: replace whole-block upsert with *append to `### Timeline`* + *replace `### KPT`* within the single `sid8` block.
3. **Reordered Stop flow** in `__main__.py` (`AutoRecap.run`): aggregate → append Timeline → substance gate → (if substantive) transcript-windowed KPT regen.
4. **Transcript windowing** — new module reading the hook's `transcript_path`, sliced by timestamp since the cursor.
5. **Prompt rewrite** — `auto_recap_compose_prompt.md` becomes a *KPT-update* prompt (prior KPT + new transcript slice + Timeline → revised KPT only), not a whole-block composer.
6. **Substance gate** replaces the lone "0 captured tool calls" check.

## Design

### Block format

```markdown
<!-- kg-recap-sid:{sid8} -->
## Session {START_HHMM}〜{END_HHMM}  {topic}

### Timeline
- {HH:MM}  {mechanical slice summary}
- {HH:MM}  {mechanical slice summary}

### KPT
- Keep: …
- Problem: …
- Try: …
<!-- /kg-recap-sid:{sid8} -->
```

- **Header line.** `START_HHMM` is fixed at first write. `END_HHMM` and `topic` are refreshed on each KPT regen (regenerable, not authoritative). When a Stop appends Timeline only (no KPT regen), `END_HHMM` still advances mechanically; `topic` is left as-is.
- **`### Timeline`.** Append-only. New bullets are inserted at the end of the section (before the next `###` or the closing marker). Never rewritten.
- **`### KPT`.** Replaced wholesale on each substantive Stop. Absent entirely until the first substantive Stop (a session that never crosses the gate has a Timeline but no KPT section).

### Marker change

`<!-- kg-recap-sid:{sid8} -->` / `<!-- /kg-recap-sid:{sid8} -->`. The existing extraction regex (`[A-Za-z0-9_-]+`) already matches a bare `sid8`. Pre-v0.16 blocks in existing notes are keyed `sid8-HHMM` and **do not collide** — they are left as historical artifacts (no migration; see Out of scope).

### Stop flow (`AutoRecap.run`)

```
1. Stop hook payload → sid8, transcript_path. (`RecapContext` gains a
   `transcript_path` field — read from the same payload that already
   yields session_id; `capture` is unaffected.)
2. KG_AUTO_RECAP gate, debounce (sid8 marker), KG_VAULT resolve,
   session-log-exists check.                                   (unchanged)
3. Read cursor → last_hhmm (or None).                          (unchanged)
4. aggregate --sid sid8 [--since last_hhmm].
   If no new entries → no-op (cursor untouched).               (reused)
5. Resolve daily-note path/anchor (discovery + cache).         (unchanged)
6. Append the aggregator's Timeline bullets to the sid8 block's
   ### Timeline section. Create the block (header + empty
   Timeline) if absent. Advance END_HHMM. — NO LLM.            (new)
7. Substance gate (see below).
   - Not substantive → write cursor, atomic-write the file,
     commit, done. KPT untouched.                              (new)
8. Substantive → read prior KPT from the block (if any) + the
   transcript slice since last_hhmm. Compose KPT-update prompt.
   Call headless claude (-p, prompt via stdin).                (new prompt)
9. Replace the block's ### KPT section with the LLM output;
   refresh END_HHMM + topic.                                   (new)
10. Atomic write, commit, push, advance cursor, touch debounce. (mostly unchanged)
```

### Substance gate (lenient)

KPT (the LLM call) runs for a Stop window when **either**:

- **durable change** — `durable_change: yes` from the aggregator (any Edit/Write, `git commit`/`git push`, or Agent dispatch), **or**
- **activity floor** — `entry_count ≥ KG_RECAP_MIN_CALLS` **or** `duration_min ≥ KG_RECAP_MIN_MINUTES`, catching substantive read-only / research sessions that conclude without an edit.

Otherwise the window is Timeline-only (step 7): the chronological trail is preserved but no boilerplate KPT is produced and no LLM is spent.

Defaults (env-overridable): `KG_RECAP_MIN_CALLS=5`, `KG_RECAP_MIN_MINUTES=5`. Rationale: capture already strips trivial tools, so a 5-call / 5-minute floor admits genuine research while excluding the 1–2 call micro-sessions that caused the flood. Pure mechanical signal — no LLM is asked "is this substantive?", keeping the gate cheap and deterministic.

### Timeline rendering (aggregate)

The aggregator emits, for the windowed slice, a compact time-ordered list. One bullet per distinct minute that has activity, summarising that minute's tools mechanically:

```
- 10:22  Edit auto_recap.py ×3, Write relay.yml
- 10:47  Bash: git commit "deploy relay", curl 疎通確認
```

Rules: file tools collapse to `path ×N`; bash shows the (already-truncated, privacy-stripped) command head; Agent shows `Agent→{subagent}`; MCP shows `{server}({n})`; errors annotate with `[err]`. No invented text — every token derives from a captured log entry. Exact grouping granularity (per-minute vs per-entry) is an implementation detail; per-minute is the default to keep long sessions readable.

### KPT-update prompt

`auto_recap_compose_prompt.md` is rewritten to emit **only** the KPT bullets (not a whole block, not markers — the recap stage owns block assembly). Inputs:

- **Prior KPT** — the current `### KPT` bullets from the block (empty on first substantive Stop).
- **Transcript slice** — conversation turns since `last_hhmm`, extracted by the new transcript module. This is the new signal that lifts KPT above mechanical boilerplate: the LLM sees *what the user was trying to do and what they learned*, not just which files changed.
- **Timeline (full, this session)** — mechanical anchor / cross-check.
- README + daily template — format only.

Instruction shape: "Here is the running KPT and what happened since the last update. **Revise** the KPT to reflect the whole session so far. Facts only; do not invent files or links; Japanese." Incremental (prior KPT + new slice) keeps per-Stop input bounded by the slice size, not the whole session — long sessions don't grow the prompt unboundedly (Mem0/Letta partial-evict shape).

### Transcript windowing (new module)

`recap/autorecap/transcript.py` (or similar):

- Input: `transcript_path` from the hook payload, `since` = cursor `HH:MM`.
- Read the JSONL transcript, keep user/assistant text turns (and tool-use *intentions* where cheap) whose timestamp maps to `HH:MM > since` for today.
- Return a plain-text slice, **capped** at a byte/char budget (truncate oldest-first within the slice) to bound prompt size and avoid the E2BIG class of failures (prompt already passed via stdin since #19).
- Best-effort: if `transcript_path` is missing/unreadable/unparseable, return empty → KPT falls back to Timeline-only signal (degrade, never crash).

### Cursor lifecycle

Unchanged from [#10](https://github.com/Kohei-Wada/knowledge-gardener/issues/10): `$XDG_STATE_HOME/knowledge-gardener/sessions/{sid8}.cursor`, single `HH:MM` line, advanced only after a successful write+commit. With coalescing the cursor still tracks "last entry folded into the block"; both the Timeline append (step 6) and the KPT regen (step 8) consume the same window, so one cursor advance per Stop covers both.

### Crash-safety

- **Atomic block write**: write the modified daily note to a temp file in the same dir and `os.replace` it, so a kill mid-write can never corrupt the note or truncate the append-only Timeline.
- Per-Stop commit is retained (already the crash-safe shape vs SessionEnd-only designs).
- A `SessionStart` sweep to recover sessions whose logs never produced a recap is **out of scope** (future); the per-Stop commit already bounds loss to the current window.

### Edge cases

- **First Stop, no cursor / no block.** Create the block (header + Timeline). Substantive → also add KPT. Cursor written after success.
- **Stop with no new entries.** Aggregator empty → no-op, cursor unchanged. (reused)
- **Stop with activity below the gate.** Timeline appended, no KPT, no LLM, cursor advanced, commit.
- **Retry after pre-commit failure.** Cursor not advanced (advanced only post-commit), so the next Stop re-aggregates the same window. Timeline append must be **idempotent for the same window** — re-appending the identical slice must not duplicate bullets. Implementation: tag each appended Timeline batch with its window-start `HH:MM`; skip if a bullet for that minute-batch already exists. KPT replace is naturally idempotent.
- **Cross-midnight.** Daily-note path resolves per `date.today()`. A Stop after midnight resolves to the new day's note and creates a fresh `sid8` block there (same session id, new day). The cursor is per-`sid8` and stores `HH:MM` only; a post-midnight `HH:MM` < pre-midnight `HH:MM` could mis-window. Accepted as a pre-existing limitation (same as #10); the new-day block simply starts from whatever the aggregator returns for the new date's log.
- **Concurrent Stops within debounce (60s).** Debounce marker skips the second firing. (unchanged)

### Backward compatibility

- Existing `sid8-HHMM` blocks in users' notes are untouched and do not collide with the new bare-`sid8` marker.
- `KG_AUTO_RECAP` opt-in unchanged; default-off installs see nothing.
- `garden-recap` (manual skill) is **not** changed here; it remains interactive. Aligning it to the two-layer block is a possible follow-up.

## Testing

- **aggregate**: Timeline render is chronological and collapses file edits to `×N`; `durable_change` flag true iff Edit/Write/commit/push/Agent present; `--since` windowing unaffected.
- **substance gate**: durable change → substantive regardless of count; below-floor read-only window → not substantive; at/above `MIN_CALLS` or `MIN_MINUTES` → substantive; env overrides honoured.
- **daily_note two-layer**: Timeline append preserves prior bullets and inserts under `### Timeline`; KPT replace swaps only `### KPT`, leaving Timeline intact; block creation when absent; END_HHMM/topic refresh.
- **idempotent retry**: re-running the same window does not duplicate Timeline bullets; KPT replace is stable.
- **transcript windowing**: slices by `since`; caps oversized slices; returns empty on missing/garbled transcript without raising.
- **integration (mocked claude + mocked log + mocked transcript)**: two substantive Stops coalesce into one block with a growing Timeline and a regenerated KPT; an interleaved micro-Stop adds a Timeline line but no KPT and spends no claude call.
- **atomic write**: a simulated failure between temp-write and replace leaves the original note intact.

## Rollout

- One spec PR (this), one plan PR, one implementation PR — matching the #10/#11/#12 cadence.
- Version bump 0.15.2 → **0.16.0** (new behaviour). Touch `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `package.json`.
- Release notes: per-session coalescing replaces per-Stop blocks; daily notes get one block per session with an append-only Timeline + a transcript-grounded KPT; contentless sessions no longer produce KPT; opt-in unchanged.

## Out of scope

- **Migration / cleanup of existing bloated notes** (2026-05-21〜05-28). Left as historical artifacts, consistent with #12's precedent. An optional, off-by-default one-shot cleanup pass can be a separate effort.
- **`SessionStart` orphan-log sweep** for crash recovery (future).
- **`garden-recap` manual-skill alignment** to the two-layer block (possible follow-up).

## Open questions

- Timeline grouping granularity (per-minute vs per-entry) — defaulting to per-minute; revisit if long sessions still read noisily.
- Transcript slice cap value — pick during implementation against a real dense session.
