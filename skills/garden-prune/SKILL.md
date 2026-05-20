---
name: garden-prune
description: Use when one or more named existing vault notes need to be removed — archived by default (git mv into the vault's documented archive folder, preserves history), hard-deleted only on explicit request. Surfaces inbound-link warnings but never auto-rewrites links. Pairs with garden-survey (find candidates) and garden-water (clean up links afterwards).
---

# Garden Prune (Delete / Archive)

Remove one or more named existing notes from the vault. Default is **archive** (soft delete via `git mv` into the vault-documented archive folder, preserving git history). **Hard delete** (`git rm`) only fires on an explicit user trigger. The vault's README still owns format conventions (link syntax, archive folder); this skill owns the decision to move or delete the file and the discipline around inbound-link warnings.

## When to Use

- User asks: "X 消して" / "X を archive して" / "archive these notes" / "stub-ssh と stub-bash を削除"
- User asks: "completely delete X" / "X を完全に削除" / "permanently remove X" / "hard delete X" — same skill, hard-delete mode
- Internal: `garden-survey` surfaced empty / stale / orphan notes → propose a prune (the user confirms each before any move/delete)

## When NOT to Use

- Searching for prune candidates (empty notes, stale fleeting, orphans) → `garden-survey`. This skill consumes a named target; it does not discover.
- Editing the contents of a note in place → `garden-water`
- Removing or rewriting a single link inside a note → `garden-water`
- Removing an MOC ↔ child link bullet — no dedicated skill today; use `garden-water` for the targeted edit
- Re-homing a note to a non-archive location → `garden-water` (or manual `git mv`)
- Pruning an asset (image, attachment, non-`.md`) — out of scope; handle manually
- Bulk-deleting an entire folder — out of scope; handle manually with `git rm -r` and a thoughtful commit message

## Process

### Step 1: Pre-flight Setup

Follow [Pre-flight Setup](../using-knowledge-gardener/SKILL.md#pre-flight-setup-shared-by-all-operational-skills) in `using-knowledge-gardener` to resolve `$KG_VAULT` and load vault conventions.

From the conventions, extract for this skill: link syntax (e.g. standard markdown `[text](path.md)` vs `[[wikilink]]`), **archive folder location** (e.g. `99_archive/`, `archive/`, `_archive/`), tag namespace (only relevant for surfacing inbound link snippets), lint rules, commit conventions.

### Step 2: Identify Target Note(s)

- **Explicit path or filename in the request**: use it. Verify each file exists; if not, stop and report — do not silently treat a missing target as a no-op.
- **Topic only**: call `garden-survey` for candidates and ask which to prune. Never silently pick.
- **Multiple targets in one invocation** (batch): allowed as long as the **mode is identical** across the batch (all archive OR all hard-delete). Mixed-mode batches must be split into separate invocations.

### Step 3: Decide Mode

- **Default**: archive (soft delete).
- **Hard delete**: only when the user uses an explicit trigger phrase ("完全に削除" / "permanently delete" / "hard delete" / "remove permanently" / "rm <file>"). When ambiguous, default to archive and surface the choice in the proposal so the user can correct.

### Step 4: Resolve Archive Destination (archive mode only)

1. Look up the archive folder name in the vault README. Do not invent one.
2. If the README does not document an archive folder: **stop**. Ask the user what folder to use, and recommend they document it in the vault README for future runs.
3. For each target, compute the destination path: `<archive-folder>/<basename>`.
4. If a file with that basename already exists at the destination: rename with a date suffix — `<basename-without-ext>.<YYYY-MM-DD>.<ext>` (e.g. `ssh-old.md` → `ssh-old.2026-05-18.md`). Surface the final name in the proposal.

### Step 5: Scan Inbound Links

For each target, scan the rest of the vault for links pointing at it. Use `rg` when available; fall back to `grep`. The exact patterns depend on the link syntax declared by the vault README.

```bash
# Substitute EXCLUDES with the vault's documented non-content folders (read from the README).
EXCLUDES=(-g '!<archive-folder>/**' -g '!<templates-folder>/**' -g '!<assets-folder>/**')

# basename match (works for both [[wikilink]] and [text](path.md) variants)
BASENAME="$(basename "$target" .md)"

if command -v rg >/dev/null 2>&1; then
  rg --type md -n "$BASENAME" "$KG_VAULT" "${EXCLUDES[@]}"
else
  grep -rn "$BASENAME" "$KG_VAULT" --include='*.md' \
    --exclude-dir=<archive-folder> --exclude-dir=<templates-folder> --exclude-dir=<assets-folder>
fi
```

Collect file + line snippets. Exclude the target file itself from the results. Exclude the archive folder (the target's future home doesn't count as an inbound link).

Do **not** edit any of the matches. This step is read-only; it produces a list for the proposal.

### Step 6: Propose, Don't Commit

Follow [Common: Propose, Don't Commit](../using-knowledge-gardener/SKILL.md#common-propose-dont-commit). For this skill, show per target:

1. Source path (absolute or `$KG_VAULT`-relative).
2. Destination path (archive mode) or `DELETE` (hard mode).
3. Inbound-link list — file + line snippet for each match, or "no inbound links found".
4. The mode (archive / hard) and a one-line rationale per target ("archive because user asked", "archive because survey flagged as empty stub", "delete hard because user said `完全に削除`").
5. The resulting commit subject.

Trigger phrases that count as implicit approval: "archive X" / "X 消して" / "delete X permanently" — show the proposal anyway (especially when inbound links exist; user may want to abort and clean up first).

### Step 7: Apply

Per target, in order:

- **Archive mode**: `git mv <source> <destination>`. The destination path is the one resolved in Step 4 (with date suffix if there was a collision). Do not `git mv` and immediately re-edit the file; leave its contents byte-for-byte identical.
- **Hard mode**: `git rm <source>`. No copy, no backup; the user explicitly chose this.

Do not stage anything else. Do not use `git add -A`.

### Step 8: Lint, Commit, Push

Follow [Common: Lint, Commit, Push](../using-knowledge-gardener/SKILL.md#common-lint-commit-push). Commit subject verb for this skill: `prune:`. Skill-specific notes:

- For archive mode, pass both the old and new paths to `pre-commit run --files`. `git mv` produces no content diff, so most lint hooks no-op.
- Verify `git status` shows only the intended renames / deletes before committing.
- One commit covers the whole logical prune operation, even in batch mode. When inbound links remain, the commit body should list them so future-you can grep for "left dangling" and route to garden-water.

### Commit Subject Examples

| Operation | Subject |
|-----------|---------|
| Archive single (no inbound) | `prune: archive ssh-deprecated` |
| Archive single (with inbound count) | `prune: archive ssh-deprecated (3 inbound links left)` |
| Archive batch | `prune: archive 5 empty fleeting notes` |
| Hard delete single | `prune: delete ssh-leaked-token (hard)` |
| Hard delete batch | `prune: delete 3 accidentally-created stubs (hard)` |

Cap at ~60 chars; put detail (target list, inbound-link locations) in the commit body when needed.

## Edge Cases

- **Target not found**: stop. Suggest the user run `garden-survey` to find the actual filename.
- **Target already in the archive folder**: for archive mode, no-op — report and skip the target. For hard-delete mode, proceed (the user explicitly wants it gone).
- **Archive folder undocumented in vault README**: stop. Ask the user what folder to use, and recommend documenting it in the vault README. Do not invent a default like `archive/`.
- **Basename collision in archive folder**: rename with date suffix (`<basename>.<YYYY-MM-DD>.<ext>`). Surface the final name in the proposal so the user sees it before approval.
- **Inbound links exist**: surface every one. Do not auto-fix; do not silently break. The user decides whether to proceed; cleanup goes through `garden-water` as separate commits.
- **Mixed-mode batch attempted** (some archive, some hard-delete): stop. Tell the user to split into two prune calls.
- **Asset / non-`.md` file requested**: stop. Out of scope; ask the user to handle manually.
- **Vault is not a git repo** (`$KG_VAULT/.git` absent): fall back to plain `mv` (archive) or `rm` (hard). Skip the pre-commit + git commit step. Warn the user that history is not preserved.
- **Pre-commit fails on a hook that touches the moved file**: investigate. `git mv` does not change content, so a failure usually means the moved file had a pre-existing lint issue in its new context (e.g. a relative link that resolved before the move and doesn't now). Either fix the link as part of the same commit (still atomic — one logical prune) or abort the prune and run `garden-water` first to fix the source, then retry.

## Key Principles

- **Archive before delete.** The vault is the user's second brain. Reversible moves beat unrecoverable removals. Hard delete requires an explicit trigger phrase, not just "delete".
- **Caller names the target.** Discovery (empty / stale / orphan) belongs to `garden-survey`. This skill consumes a named target list and acts. The composed workflow `survey → prune` is intentional, not a defect.
- **Surface inbound links, do not fix them.** Each broken link is a separate editorial decision (drop the bullet? rewrite the path? promote the link to a stub redirect?) and belongs in `garden-water`. A prune that silently rewrites N other files is not atomic.
- **One mode per invocation.** Mixed-mode batches hide intent in commit history. Split.
- **Format from vault, never from this skill.** Archive folder name, link syntax — all from the vault README. If the README does not document the archive folder, stop and ask.
- **`git mv`, not copy-then-delete.** Preserve history. The diff should be a pure rename, no content changes.
- **Never bypass lint.** Pre-commit failures committed in are technical debt the next reader inherits.
- **Cite the trigger.** Internally know whether this came from the user, from `garden-survey` finding empty notes, or from a consolidation in `garden-water`. Use that to write a meaningful commit subject and rationale.
