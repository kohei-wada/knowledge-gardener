# garden-prune — Design

- **Date**: 2026-05-18
- **Status**: Approved (pending spec review)
- **Target release**: knowledge-gardener v0.6.0
- **Sibling skills**: [garden-plant](../../skills/garden-plant/SKILL.md) (C), [garden-survey](../../skills/garden-survey/SKILL.md) (R), [garden-water](../../skills/garden-water/SKILL.md) (U), [garden-connect](../../skills/garden-connect/SKILL.md) (link), [garden-recap](../../skills/garden-recap/SKILL.md) (session wrap-up)

## Goal

Ship the **Delete** operation of the CRUD set as `garden-prune`. After this release CRUD is complete (C/R/U/D = plant / survey / water / prune) and the linking primitive (connect) plus the session wrap-up (recap) round out the skill family.

## Scope

garden-prune removes one or more named existing notes from the vault — by default **archiving** (soft delete, `git mv` into the vault's documented archive folder), and only **hard-deleting** (`git rm`) when the user asks for it explicitly.

### In scope (v0.6.0)

- Soft delete (default): `git mv <source> <archive-folder>/<source-basename>` for one named note. Preserves git history; the note is recoverable by `git mv` back. The archive folder name comes from the vault README.
- Hard delete (explicit only): `git rm <source>` when the user says "完全に削除" / "permanently delete" / "hard delete" / equivalent.
- Batch over a single mode: prune N named notes in one commit, as long as the mode (archive vs hard-delete) is identical across the batch.
- Incoming-link scan: before proposing, scan the rest of the vault for inbound references to each target. Surface the list in the proposal so the user can decide whether to proceed (and route to garden-water for cleanup separately).

### Out of scope (deferred or delegated)

- Auto-discovery of prune candidates (empty notes, stale fleeting notes, orphan notes). This is `garden-survey`'s job — the caller names the targets; garden-prune does not infer. The composed workflow is `survey → prune`.
- Rewriting or removing inbound links from other notes that pointed at the pruned target. garden-prune surfaces them as warnings; cleanup belongs in garden-water (one inbound-link edit at a time keeps commits atomic and reviewable).
- Bulk delete of an entire folder. Out of scope; the user should do it manually with `git rm -r` and a thoughtful commit message.
- Restoring an archived note. Recovery is a manual `git mv` back; no skill for it.
- Pruning an asset (image, attachment). Out of scope; this skill targets `.md` notes only.

## Why archive-by-default, not delete-by-default

The user's vault is their second brain. A pure delete is unrecoverable without git surgery and breaks every inbound link silently. An archive (move into a documented archive folder) preserves the file, preserves history, keeps inbound links valid (the file still exists at the new path — they just need a path update, which the user can decide is worth doing or not), and is the standard PKM convention.

Hard delete is reserved for cases where the user has consciously decided the note should not exist at all (e.g. accidentally created, sensitive content, deduplication consolidation already done in garden-water). Requiring an explicit phrase prevents accidental destruction.

## Why caller-names-the-target (no discovery)

Mirrors garden-connect's "caller names the pair" principle. Discovery and removal are different concerns:

- Discovery (find empty notes, find stale fleeting notes, find orphans) is **search**, owned by garden-survey.
- Removal is **action**, owned by garden-prune.

Composing them keeps each skill single-purpose. The user's typical phrasing for the discovery question ("空ノート探して消して") is handled by routing: `using-knowledge-gardener` directs to survey first, then to prune with the survey results as input. The user confirms each side.

## Behavioral Defaults

### Mode

- **Default**: archive (soft). `git mv` into the vault's documented archive folder.
- **Hard delete**: only when the user explicitly says so. Trigger phrases include "完全に削除" / "permanently delete" / "hard delete" / "remove permanently" / "rm". When unsure, treat as archive and surface in the proposal.

### Archive destination

- The vault README must document an archive folder convention (e.g. `99_archive/`, `archive/`, `_archive/`, or whatever name). garden-prune reads it from the README — never invents a default.
- If the README does not document one and the user asked for archive (or did not specify): **stop and ask** what the archive folder should be (and recommend that the user document the choice in the vault README for future runs).
- Archive preserves the source basename. If a file with the same basename already exists in the archive folder, append a disambiguator (the YYYY-MM-DD of the prune) before the extension, e.g. `ssh-old.md` → `ssh-old.2026-05-18.md`. Surface this in the proposal so the user sees the final name.

### Incoming-link scan

- Before proposing, run an inbound-link scan across the vault for each target. Use `rg --type md -l` over the vault, looking for any string that matches the target's basename or the relative path in the link syntax declared by the vault README (`[[wikilink]]` and/or `[text](path.md)`).
- Surface every match in the proposal (file + line snippet). Do **not** edit them.
- If the user proceeds anyway, the commit body should mention the count so the impact is recorded ("3 inbound links left dangling — clean up via garden-water").

### Batch

- Allowed when: same mode (all archive or all hard-delete), each target named explicitly. One commit, subject pluralized.
- Not allowed: mixed mode in one invocation. Split into two prune calls.
- Bi (paired) prune of MOC ↔ child is **not** a special case — pruning a MOC does not also prune its children. Each is a separate decision.

## Process (mirrors garden-connect shape)

1. **Resolve vault path** — `KG_VAULT`, fail loud if unset.
2. **Load vault conventions** — `$KG_VAULT/README.md`, parent `README.md`, `CLAUDE.md`, target folder's `README.md` if present. Extract link syntax, archive folder name, Versioning Discipline.
3. **Identify target note(s)** — explicit path or filename preferred. If only a topic is given, call garden-survey for candidates and ask which.
4. **Verify each target exists** — if not, stop and report. Do not silently treat a missing target as a no-op.
5. **Decide mode** — archive (default) vs hard-delete (only on explicit trigger phrase). When the request is ambiguous, default to archive and surface the choice in the proposal.
6. **Resolve archive destination** (archive mode only) — read from vault README; stop and ask if undocumented; handle basename collision via date-suffix disambiguator.
7. **Scan inbound links** — `rg --type md -l` over the vault for each target's basename and (per link syntax) relative path. Collect file + line snippets.
8. **Propose** — show per-target source path, destination path (archive) or "DELETE" (hard), inbound-link list with snippets, mode rationale, and the resulting commit subject. Exception: if the user explicitly named the targets and the mode ("archive X" / "delete X permanently"), that counts as approval, but still show the proposal in the response so the user can correct.
9. **Apply** — `git mv <src> <dst>` (archive) or `git rm <src>` (hard) for each target. One staging operation per target file; no `git add -A`.
10. **Lint, commit, push** — `pre-commit run --files <every changed path>` (never `--no-verify`), `git commit -m "prune: ..."` per the subject table below. Single commit per logical operation.

## Commit Subjects

| Operation | Subject |
|-----------|---------|
| Archive single (no inbound) | `prune: archive ssh-deprecated` |
| Archive single (with inbound count) | `prune: archive ssh-deprecated (3 inbound links left)` |
| Archive batch | `prune: archive 5 empty fleeting notes` |
| Hard delete single | `prune: delete ssh-leaked-token (hard)` |
| Hard delete batch | `prune: delete 3 accidentally-created stubs (hard)` |

Cap at ~60 chars; detail in commit body when needed. When inbound links remain, the commit body should list them so future-you can grep for "left dangling" and route to garden-water.

## Edge Cases

- **Target not found**: stop. Suggest the user run garden-survey to find the actual filename.
- **Target is already in the archive folder**: for archive mode, no-op — report and skip. For hard-delete mode, proceed (the user explicitly wants it gone).
- **Archive folder undocumented in vault README**: stop. Ask the user what folder to use, and recommend documenting it in the vault README. Do not invent a default like `archive/`.
- **Basename collision in archive folder**: rename with date suffix (`<basename>.<YYYY-MM-DD>.md`). Surface the final name in the proposal.
- **Inbound links exist**: surface every one. Do not auto-fix; do not silently break. The user decides whether to proceed and then cleans up via garden-water.
- **Target has a Related/MOC back-reference structure** (i.e. the note links out to its MOCs and other peers): pruning is fine — the outbound links inside the moved file remain valid because the moved file points to other files that still exist. No special handling needed.
- **Pre-commit reformats**: `git mv` produces no diff inside file bytes, so most lint hooks no-op. `check-skill-refs` should pass because no namespaced skill references move (the prune skill's body uses bare names like `garden-water`, not the `knowledge-gardener:` prefix). If a hook does change something, re-stage and retry.
- **Mixed-mode batch attempted** (some archive, some hard-delete): stop. Tell the user to split into two prune calls.
- **Asset / non-`.md` file requested**: stop. Out of scope; ask the user to handle manually.
- **Vault is not a git repo**: fall back to `mv` (archive) or `rm` (hard delete). Skip the pre-commit + git commit step but warn the user that history is not preserved. (Same fallback shape as the other skills when `$KG_VAULT/.git` is absent.)

## Boundary with sibling skills (re-statement)

| If the request is… | Use |
|--------------------|-----|
| "Find empty notes" / "list stale fleeting" | `garden-survey` |
| "Find empty notes and delete them" | `garden-survey` then `garden-prune` (two-step) |
| Move a note to a different non-archive location (re-home) | `garden-water` (or manual `git mv`) — not prune |
| Remove a single link from inside a note | `garden-water` |
| Remove an MOC ↔ child link bullet | `garden-water` (until a future `garden-disconnect` ships; not on this roadmap) |
| Permanently delete a note | `garden-prune` with explicit hard-delete trigger |
| Archive a stale or superseded note | `garden-prune` (default mode) |

garden-water's existing "When NOT to Use" entry that says `garden-prune (when shipped)` has its parenthetical removed by this release. garden-connect's equivalent entry is also updated.

## Release Checklist (knowledge-gardener v0.6.0)

1. New `skills/garden-prune/SKILL.md` per this design.
2. Update `skills/using-knowledge-gardener/SKILL.md`:
   - Add garden-prune row to the Available Skills table.
   - Add routing entries for "archive X" / "delete X" / "完全に削除" / internal "garden-survey surfaced empty/stale notes" trigger.
   - Drop the "(One more CRUD skill — `garden-prune` … — is planned)" footnote.
3. Update `skills/garden-water/SKILL.md`: drop the "(when shipped)" qualifier on the existing garden-prune mention.
4. Update `skills/garden-connect/SKILL.md`: drop the "(when shipped)" qualifier on the existing garden-prune mention.
5. Update root `README.md`: flip the `garden-prune` row from `(planned)` to `(implemented)`.
6. Update `CLAUDE.md`: drop the "Planned (not yet shipped)" line entirely — CRUD is now complete.
7. Bump `package.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` from `0.5.3` → `0.6.0` atomically.
8. Commit, tag `v0.6.0`, push.

## Open Questions

None at design time; all branches have a default and a documented override.

## Non-goals

- A general-purpose file mover. Re-homing notes lives in garden-water or manual `git mv`.
- A bulk cleanup engine. Composed workflow `survey → prune` covers the common cases; resist the temptation to grow garden-prune into "find and delete by predicate".
- Automatic inbound-link cleanup. Each broken link is a separate decision (delete the bullet? rewrite to the new archive path? promote the link to a redirect note?) and belongs in garden-water.
- A `garden-disconnect` shortcut for removing a single MOC ↔ child bullet. Not on this roadmap; garden-water handles it today.
