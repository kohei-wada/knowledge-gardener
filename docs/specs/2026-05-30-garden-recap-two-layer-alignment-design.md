# garden-recap Two-Layer Block Alignment — Design

- **Date**: 2026-05-30
- **Status**: Draft
- **Target release**: knowledge-gardener v0.17.0
- **Prior art**: [2026-05-30-recap-session-coalesce-design.md](2026-05-30-recap-session-coalesce-design.md) (the auto-recap two-layer block this aligns to)

## Problem

The auto-recap `Stop` hook (since v0.16.0) writes one coalesced block per session, keyed `<!-- kg-recap-sid:{sid8} -->`, with two layers: an append-only mechanical `### Timeline` and a transcript-grounded `### KPT`.

The **manual** `garden-recap` skill still drafts a free-form, template-driven recap from recollection — no markers, no Timeline, a different shape. Running both on the same day produces two divergent recap formats in the daily note, and a manual wrap-up cannot extend or correct the block auto-recap already wrote for the active session.

The v0.16.0 spec flagged this as a follow-up: *"garden-recap manual-skill alignment to the two-layer block."* This is that follow-up.

## Goal

A manual `garden-recap` for the active session **updates the same `kg-recap-sid:{sid8}` block** auto-recap uses — appending the session's Timeline (deduped) and replacing the KPT with one the assistant authors from the full conversation. Manual and auto recaps converge on one block per session. When no block exists yet (auto-recap off, or first wrap-up before any Stop), garden-recap creates it.

Manual recap keeps its interactive contract: **propose the diff, get approval, then write** (unlike the silent hook).

## Approach (chosen: B — update the same block)

garden-recap runs in the main session, so the assistant **is** the LLM — no headless `claude` call is needed (this is the key difference from the hook, which spawns `claude -p`). The skill reuses the block machinery built for auto-recap and supplies the KPT directly.

Reused as-is (all from v0.16.0, already tested):
- `recap.aggregate` (`--json`) — mechanical Timeline + `first_hhmm`/`last_hhmm`/`sid8` for a session.
- `recap.autorecap.block.upsert_session_block` — two-layer surgery (Timeline append-dedup, KPT replace, byte-idempotent, legacy `{sid8}-{HHMM}` non-collision).
- `recap.autorecap.daily_note.DailyNote.apply_block` / `.commit` (atomic write, commit/push).
- `recap.shared.cursor.write_cursor`.

New: one thin CLI, `recap.manual_recap` (a `__main__.py` under a new `recap/manual_recap/` package, mirroring the existing per-stage package layout), that the skill drives.

## Design

### New CLI: `python -m recap.manual_recap`

The skill resolves the daily-note path itself (it already does this from the vault README in its current Step 1/3), so the CLI takes the resolved path explicitly and has **no dependency on README discovery or any LLM** — keeping it deterministic and headless-free.

Arguments:
- `--sid <sid8>` — the active session (skill obtains it from the aggregator's default-latest `sessions[0].sid8`).
- `--daily-path <abs path>` — today's daily note, already resolved by the skill.
- `--kpt-file <path>` — a file containing the `### KPT` section the assistant authored.
- `--insert-before <heading>` — optional anchor for a newly-created block (default: append at EOF).
- `--dry-run` — print the resulting daily-note **diff** to stdout and exit without writing.
- `--no-commit` — write the file but skip git (parity with the hook's `KG_AUTO_RECAP_NO_PUSH` testing needs).

Behaviour:
1. Run the aggregator in-process for `--sid` over the **full session** (no `--since`) → `timeline` bullets, `first_hhmm`, `last_hhmm`. If the session has zero entries → exit non-zero with a clear "nothing to recap" message (skill surfaces it; no empty block).
2. Read the KPT section from `--kpt-file`.
3. Derive `topic` from the KPT's first `Keep:` bullet (reuse the hook's `_topic_from_kpt` logic — extract it to a shared helper so both call sites share one implementation).
4. `existing = daily_path.read_text()` (or "" if absent). `new = upsert_session_block(existing, sid8, start_hhmm=first, end_hhmm=last, topic=topic, timeline_bullets=timeline, kpt_section=<kpt>, insert_before=<anchor>)`.
5. `--dry-run`: print a unified diff of `existing` → `new` and exit 0. Write nothing.
6. Otherwise: `DailyNote(vault, daily_path).apply_block(...)` (atomic), `.commit(sid8, first, topic)` unless `--no-commit`, then `write_cursor(sid8, last)`.

`vault` for `DailyNote` (needed for repo-root detection) is `KG_VAULT`.

### Cursor advance

After a successful manual write, `write_cursor(sid8, last_hhmm)` advances the cursor to the session end. Consequence: the next auto `Stop` sees only **new** activity since the wrap-up, takes the assistant-authored KPT as its `prior KPT`, and refines (not discards) it. The user's manual curation persists and is extended, never silently overwritten. Timeline dedup means the auto Stop re-appends nothing already present.

### Skill rewrite (`skills/garden-recap/SKILL.md`)

The skill's process becomes:
1. **Pre-flight** (unchanged): resolve `$KG_VAULT`, load conventions, resolve today's daily-note path.
2. **Identify the session**: `python -m recap.aggregate --json` (default = latest session) → read `sessions[0].sid8`. If `0 session(s)`/no entries (no capture log — legacy install or pre-`v0.8.0` session) → the two-layer path can't produce a mechanical Timeline, so **fall back to the current recollection-based template recap** (the skill's existing behaviour) as a graceful degradation. The two-layer block path applies whenever a session log exists (the normal case).
3. **Author the KPT**: the assistant writes the `### KPT` section (Keep/Problem/Try per the vault's KPT convention) from the full conversation — richer than the hook's transcript slice. Cap per the existing "~5 items" rule.
4. **Preview**: write the KPT to a temp file, run `python -m recap.manual_recap --sid … --daily-path … --kpt-file … --dry-run`, show the diff to the user with a one-line rationale (per "Propose, Don't Commit").
5. **Apply on approval**: re-run without `--dry-run`. The CLI writes + commits + advances the cursor.

The recollection-fallback machinery (3b) is retained only for the no-log case; the Timeline-driven path (aggregator) is primary, matching the current skill's existing 3a/3b split.

### What changes vs the current skill

- Output shape: from a free-form template-section fill to the two-layer `kg-recap-sid:{sid8}` block (Timeline + KPT). The KPT bullets still follow the vault's KPT convention.
- The skill no longer hand-edits the daily note via Edit/Write; it delegates the write to `recap.manual_recap` so formatting/idempotency/legacy-non-collision come from the one tested implementation.

### Shared-helper extraction

`_topic_from_kpt` currently lives as a private static on `AutoRecap`. Move it to a small shared module (e.g. `recap/autorecap/block.py` as a public `topic_from_kpt`, since it operates on a KPT section string) and have both `AutoRecap` and `manual_recap` import it. No behaviour change — pure de-duplication.

## Format-agnostic note

The two-layer block (markers + `## Session` header + `### Timeline`) is a structure the gardener **imposes**, not one read from the vault template — auto-recap already does this. Only the KPT sub-section follows the vault's documented KPT convention. Aligning garden-recap therefore moves the manual flow from "template-driven" to "gardener-imposed two-layer block," consistent with auto-recap. This assumes the vault's daily note uses a KPT-style recap — the **same assumption auto-recap already makes**. Vaults whose daily notes don't use KPT are out of scope here (as they already are for auto-recap).

## Testing

New `tests/test_manual_recap.py` (subprocess + tmp vault, mirroring `test_auto_recap.py` helpers):
- **create**: no existing block → a `kg-recap-sid:{sid8}` block with Timeline + the supplied KPT is created.
- **update/coalesce**: an existing auto-written block for the same sid → Timeline deduped (no duplicate bullets), KPT replaced with the manual one, header end/topic refreshed, single block.
- **dry-run**: prints a diff and writes nothing (file unchanged, no commit, cursor unchanged).
- **cursor advance**: after a real run, the cursor equals the session's `last_hhmm`.
- **empty session**: zero-entry / missing log → non-zero exit, no block written.
- **legacy non-collision**: a pre-existing `kg-recap-sid:{sid8}-{HHMM}` block is left untouched; a new bare-sid block is created beside it.
- **topic_from_kpt** shared helper: covered by the existing block/auto tests after extraction; add a direct unit test for the public function.

## Rollout

- One spec PR (this), one plan PR, one implementation PR — matching the established cadence.
- Version bump 0.16.1 → **0.17.0** (new user-facing behaviour in the manual skill).
- Release notes: garden-recap now writes/updates the same per-session two-layer block as auto-recap; manual wrap-ups coalesce with the hook's block instead of producing a divergent format.

## Out of scope

- Migration/cleanup of historical divergent manual recaps already in past daily notes (left as artifacts, per the v0.16.0 precedent).
- Changing auto-recap behaviour (this only adds a manual path that reuses its machinery).
- Supporting non-KPT daily-note templates (same limitation as auto-recap).

## Open questions

- Commit subject for the manual path: reuse `build_commit_subject` (yields `water: {date} {HH:MM} 〜 {topic}`) as-is, or tag it `(manual)`. Leaning reuse-as-is for consistency with auto; revisit if distinguishing manual vs auto commits proves useful.
