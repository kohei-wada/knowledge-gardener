# garden-prune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `garden-prune` skill (the Delete operation of CRUD) as knowledge-gardener v0.6.0. Scope is named-target deletion only (archive by default, hard-delete on explicit request); discovery of prune candidates stays with garden-survey.

**Architecture:** Pure skill-library plugin — no code, no tests in the traditional sense. Deliverable is a new `skills/garden-prune/SKILL.md` plus cross-skill doc updates (using-knowledge-gardener routing, garden-water + garden-connect boundary clarifications, top-level README + CLAUDE.md skill tables, version bump). Pre-commit hooks (`check-skill-refs`, `check-skill-frontmatter`, `check-version-sync`) serve as the test suite.

**Tech Stack:** Markdown + YAML frontmatter, bash pre-commit scripts, git for atomic commits per the vault's Versioning Discipline.

**Source spec:** `docs/specs/2026-05-18-garden-prune-design.md`

**Working directory:** `~/ghq/github.com/Kohei-Wada/knowledge-gardener`

---

## File Structure

| Path | Action | Responsibility |
|------|--------|----------------|
| `skills/garden-prune/SKILL.md` | Create | The new skill's behavior, identical structural shape to `skills/garden-connect/SKILL.md` |
| `skills/using-knowledge-gardener/SKILL.md` | Modify | Add garden-prune to Available Skills table + Skill Routing block; remove the "planned" footnote line |
| `skills/garden-water/SKILL.md` | Modify | Drop the "(when shipped)" qualifier on the existing garden-prune mention |
| `skills/garden-connect/SKILL.md` | Modify | Drop the "(when shipped)" qualifier on the existing garden-prune mention |
| `README.md` | Modify | Flip `garden-prune` row from `(planned)` to `(implemented)` in the Skills table |
| `CLAUDE.md` | Modify | Drop the "Planned (not yet shipped): `garden-prune`" line entirely — CRUD is complete |
| `package.json` | Modify | `version: "0.5.3"` → `"0.6.0"` |
| `.claude-plugin/plugin.json` | Modify | `version: "0.5.3"` → `"0.6.0"` |
| `.claude-plugin/marketplace.json` | Modify | `plugins[0].version: "0.5.3"` → `"0.6.0"` |

**Commit discipline (mandatory per `CLAUDE.md` Versioning Discipline):**
- One logical change per commit. Pre-commit must pass; never `--no-verify`.
- Each commit is `git add <specific files>` then `git commit -m "..."`. No `git add -A`.
- The 3 version files (`package.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) MUST move together in a single commit — the `check-version-sync` hook fails otherwise.
- Tag `v0.6.0` is applied after the version-bump commit lands and is pushed separately (`git push --tags`).

**Commit order matters:** Task 1 creates the new skill directory first so that pre-commit's `check-skill-refs.sh` (which validates every namespaced skill reference against existing `skills/*/` dirs) does not fail when Task 2 adds the cross-skill references.

**Reference-syntax gotcha (carried from the connect plan):** `check-skill-refs.sh` greps for the regex `knowledge-gardener:[a-z][a-z0-9-]*` across all `.md`/`.json`/`.sh` files in the tree. Any literal occurrence of that pattern — even inside a code block, a quoted example, or a comment — counts as a reference and must resolve to an existing `skills/<name>/` directory. When writing the new SKILL.md, refer to sibling skills as bare names (`garden-water`, `garden-survey`) in prose, and only use the `knowledge-gardener:` prefix when the name actually exists as a directory. If a check-skill-refs failure surfaces an unexpected match, grep the tree for it first — it's almost always a literal in your own freshly added prose.

---

### Task 1: Create the garden-prune skill

**Files:**
- Create: `skills/garden-prune/SKILL.md`

- [ ] **Step 1: Confirm clean tree**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git status --short
```

Expected: clean working tree (only the spec committed in `bb50a2d`).

- [ ] **Step 2: Create the skill file**

Write `skills/garden-prune/SKILL.md` with the following exact content:

````markdown
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

### Step 1: Resolve Vault Path

1. Read `OBSIDIAN_VAULT` environment variable. If unset: stop and tell the user to set it.
2. Verify the directory exists. If not: stop and report the missing path.

Refer to this path as `$KG_VAULT` for the rest of this skill.

### Step 2: Load Vault Conventions

Read in order, stopping when you have enough:

1. `$KG_VAULT/README.md` (vault-root, most specific)
2. `$KG_VAULT/../README.md` (parent — many vaults live under a git repo)
3. `$KG_VAULT/CLAUDE.md` or `$KG_VAULT/../CLAUDE.md` (operational instructions including Versioning Discipline)
4. The target folder's `README.md` if it exists

Extract: link syntax (e.g. standard markdown `[text](path.md)` vs `[[wikilink]]`), **archive folder location** (e.g. `99_archive/`, `archive/`, `_archive/`), tag namespace (only relevant for surfacing inbound link snippets), lint rules, commit conventions.

### Step 3: Identify Target Note(s)

- **Explicit path or filename in the request**: use it. Verify each file exists; if not, stop and report — do not silently treat a missing target as a no-op.
- **Topic only**: call `garden-survey` for candidates and ask which to prune. Never silently pick.
- **Multiple targets in one invocation** (batch): allowed as long as the **mode is identical** across the batch (all archive OR all hard-delete). Mixed-mode batches must be split into separate invocations.

### Step 4: Decide Mode

- **Default**: archive (soft delete).
- **Hard delete**: only when the user uses an explicit trigger phrase ("完全に削除" / "permanently delete" / "hard delete" / "remove permanently" / "rm <file>"). When ambiguous, default to archive and surface the choice in the proposal so the user can correct.

### Step 5: Resolve Archive Destination (archive mode only)

1. Look up the archive folder name in the vault README. Do not invent one.
2. If the README does not document an archive folder: **stop**. Ask the user what folder to use, and recommend they document it in the vault README for future runs.
3. For each target, compute the destination path: `<archive-folder>/<basename>`.
4. If a file with that basename already exists at the destination: rename with a date suffix — `<basename-without-ext>.<YYYY-MM-DD>.<ext>` (e.g. `ssh-old.md` → `ssh-old.2026-05-18.md`). Surface the final name in the proposal.

### Step 6: Scan Inbound Links

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

### Step 7: Propose, Don't Commit

**Default: do not write directly.** Show the user, per target:

1. Source path (absolute or `$KG_VAULT`-relative).
2. Destination path (archive mode) or `DELETE` (hard mode).
3. Inbound-link list — file + line snippet for each match, or "no inbound links found".
4. The mode (archive / hard) and a one-line rationale per target ("archive because user asked", "archive because survey flagged as empty stub", "delete hard because user said `完全に削除`").
5. The resulting commit subject.

Ask for approval. Apply only after the user confirms.

**Exception:** an explicit "archive X" / "X 消して" / "delete X permanently" request counts as approval for the named targets. Still show the proposal in the response so the user can correct (especially if inbound links exist — they may want to abort and clean up first).

### Step 8: Apply

Per target, in order:

- **Archive mode**: `git mv <source> <destination>`. The destination path is the one resolved in Step 5 (with date suffix if there was a collision). Do not `git mv` and immediately re-edit the file; leave its contents byte-for-byte identical.
- **Hard mode**: `git rm <source>`. No copy, no backup; the user explicitly chose this.

Do not stage anything else. Do not use `git add -A`.

### Step 9: Lint, Commit, Push

Per the vault's Versioning Discipline (declared in `$KG_VAULT/../CLAUDE.md` when present):

1. `pre-commit run --files <every changed path>` — both the old path (now-removed or now-moved) and the new path (for archive) should be passed. Do not bypass with `--no-verify`. `git mv` produces no content diff, so most lint hooks no-op.
2. Verify `git status` shows only the intended renames or deletes.
3. `git commit -m "prune: <subject>"` — see the table below for the subject shape. One commit covers the whole logical prune operation, even when it spans N targets in batch mode. When inbound links remain, the commit body should list them so future-you can grep for "left dangling" and route to garden-water.
4. `git push` to the configured remote.

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
````

- [ ] **Step 3: Run pre-commit on the new file**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/garden-prune/SKILL.md
pre-commit run --files skills/garden-prune/SKILL.md
```

Expected: all hooks pass. In particular:
- `check-skill-frontmatter`: PASS (the file has `name:` and `description:`).
- `check-skill-refs`: PASS. The new file references `garden-water` and `garden-survey` only as bare names (no `knowledge-gardener:` prefix), so no cross-skill resolution is required from this file. If the hook does fail, grep for `knowledge-gardener:` inside `skills/garden-prune/SKILL.md` and convert any namespaced mention to a bare name.
- `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`: PASS.

- [ ] **Step 4: Commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git commit -m "feat: garden-prune skill — delete/archive primitive

Archive by default (git mv into vault-documented archive folder, preserves
git history); hard delete only on explicit user trigger. Surfaces inbound
links but does not auto-rewrite them — link cleanup is garden-water's job,
one atomic edit per commit. Caller (user or garden-survey) names the
target; this skill does not discover prune candidates."
```

Expected: commit succeeds, pre-commit passes, single file added.

---

### Task 2: Route garden-prune from using-knowledge-gardener

**Files:**
- Modify: `skills/using-knowledge-gardener/SKILL.md`

- [ ] **Step 1: Add the row to the Available Skills table**

Use the Edit tool. `old_string`:

```
| `knowledge-gardener:garden-connect` | Link an existing MOC and an existing child note (atomic graph-edge insertion, bi-directional by default) |
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |
```

`new_string`:

```
| `knowledge-gardener:garden-connect` | Link an existing MOC and an existing child note (atomic graph-edge insertion, bi-directional by default) |
| `knowledge-gardener:garden-prune` | Remove an existing note — archive by default (git mv into the vault's archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; never auto-rewrites links |
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |
```

- [ ] **Step 2: Drop the "planned" footnote line**

Use the Edit tool. `old_string`:

```
(One more CRUD skill — `garden-prune` (delete/archive) — is planned and will appear here as it ships.)
```

`new_string`:

```
CRUD is complete: garden-plant (C), garden-survey (R), garden-water (U), garden-prune (D). garden-connect adds the link primitive; garden-recap handles session wrap-up.
```

- [ ] **Step 3: Add routing entries**

Use the Edit tool. `old_string`:

```
(internal — garden-plant created a child that belongs under an existing MOC)
  → garden-connect (propose as follow-up to the new note)

"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap
```

`new_string`:

```
(internal — garden-plant created a child that belongs under an existing MOC)
  → garden-connect (propose as follow-up to the new note)

"X 消して" / "X を archive して" / "archive these notes" / "X を完全に削除" / "permanently delete X"
  → garden-prune

(internal — garden-survey surfaced empty / stale / orphan notes worth removing)
  → garden-prune (propose per target; require user confirmation; never auto-prune)

"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap
```

- [ ] **Step 4: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/using-knowledge-gardener/SKILL.md
pre-commit run --files skills/using-knowledge-gardener/SKILL.md
git commit -m "docs(using-kg): route garden-prune (table + routing block)"
```

Expected: pre-commit passes (`check-skill-refs` now finds the new `garden-prune` references and resolves them against the `skills/garden-prune/` dir created in Task 1).

---

### Task 3: Drop "(when shipped)" qualifier in garden-water

**Files:**
- Modify: `skills/garden-water/SKILL.md`

- [ ] **Step 1: Patch the qualifier**

Use the Edit tool. `old_string`:

```
- Removing or archiving a note → `garden-prune` (when shipped) or manual
```

`new_string`:

```
- Removing or archiving a note → `garden-prune`
```

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/garden-water/SKILL.md
pre-commit run --files skills/garden-water/SKILL.md
git commit -m "docs(water): garden-prune is shipped"
```

---

### Task 4: Drop "(when shipped)" qualifier in garden-connect

**Files:**
- Modify: `skills/garden-connect/SKILL.md`

- [ ] **Step 1: Patch the qualifier**

Use the Edit tool. `old_string`:

```
- Removing or rewriting an existing link → `garden-prune` (when shipped) for removal, `garden-water` for rewrite
```

`new_string`:

```
- Removing or rewriting an existing link → `garden-water` (no dedicated MOC ↔ child link-removal skill exists; use garden-water to drop the bullet, and garden-prune only when the *whole note* should go)
```

The wording shift is intentional: `garden-prune` removes whole notes, not individual links, so the original sentence was misleading even when prune ships. Removing the bullet from a MOC stays in garden-water territory.

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/garden-connect/SKILL.md
pre-commit run --files skills/garden-connect/SKILL.md
git commit -m "docs(connect): garden-prune is shipped (and is whole-note only)"
```

---

### Task 5: Update top-level README skill table

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Flip the garden-prune row from planned to implemented**

Use the Edit tool. `old_string`:

```
| `garden-prune` | **(planned)** Identify and propose deletion/archive of stale or orphan notes |
```

`new_string`:

```
| `garden-prune` | **(implemented)** Remove a named note — archive by default (git mv into the vault's archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; cleanup goes through garden-water |
```

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add README.md
pre-commit run --files README.md
git commit -m "docs(readme): mark garden-prune as implemented"
```

---

### Task 6: Update CLAUDE.md skill table

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add garden-prune row and remove the "Planned" line**

Use the Edit tool. `old_string`:

```
| garden-connect | Links an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
| garden-recap | Wraps up a session by writing what was worked on to today's daily note, so the next session can pick up context |

Planned (not yet shipped): `garden-prune` (delete/archive).
```

`new_string`:

```
| garden-connect | Links an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
| garden-prune | Removes a named note — archive by default (git mv into the vault's documented archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; link cleanup is garden-water's job |
| garden-recap | Wraps up a session by writing what was worked on to today's daily note, so the next session can pick up context |
```

(The "Planned (not yet shipped)" line is removed entirely — CRUD is now complete.)

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add CLAUDE.md
pre-commit run --files CLAUDE.md
git commit -m "docs(claude): add garden-prune row; drop Planned line (CRUD complete)"
```

---

### Task 7: Bump version to 0.6.0

The 3 version files must move atomically — the `check-version-sync` hook fails on any mismatch. Use the repo's `scripts/bump-version.sh` if it accepts an explicit target version; otherwise patch by hand.

**Files:**
- Modify: `package.json`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Bump (preferred path — use the helper)**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
./scripts/bump-version.sh 0.6.0   # or whatever the script's argument convention is — `--help` first if unsure
```

If the script does the commit for you, skip Steps 2–5 and jump to Task 8. If it only edits files, continue below.

- [ ] **Step 2: Manual bump — package.json**

Use the Edit tool. `old_string`:

```
  "version": "0.5.3",
  "type": "module"
```

`new_string`:

```
  "version": "0.6.0",
  "type": "module"
```

- [ ] **Step 3: Manual bump — .claude-plugin/plugin.json**

Use the Edit tool. `old_string`:

```
  "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
  "version": "0.5.3",
```

`new_string`:

```
  "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
  "version": "0.6.0",
```

- [ ] **Step 4: Manual bump — .claude-plugin/marketplace.json**

Use the Edit tool. `old_string`:

```
      "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
      "version": "0.5.3",
```

`new_string`:

```
      "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
      "version": "0.6.0",
```

- [ ] **Step 5: Run pre-commit on the 3 version files and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
pre-commit run --files package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(release): bump 0.5.3 -> 0.6.0 (garden-prune)"
```

Expected: `check-version-sync` PASS (all three read `0.6.0` now). If it fails, one of the Edits did not land — re-Read the failing file and patch.

---

### Task 8: Push and tag v0.6.0

- [ ] **Step 1: Sanity check the commit graph**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git log --oneline -10
```

Expected (most recent first):

```
<hash> chore(release): bump 0.5.3 -> 0.6.0 (garden-prune)
<hash> docs(claude): add garden-prune row; drop Planned line (CRUD complete)
<hash> docs(readme): mark garden-prune as implemented
<hash> docs(connect): garden-prune is shipped (and is whole-note only)
<hash> docs(water): garden-prune is shipped
<hash> docs(using-kg): route garden-prune (table + routing block)
<hash> feat: garden-prune skill — delete/archive primitive
bb50a2d docs(prune): design spec for garden-prune (v0.6.0)
6d2c48a chore(release): bump 0.5.2 -> 0.5.3
```

If any commit is out of order or missing, stop and fix before pushing or tagging.

- [ ] **Step 2: Push commits**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git push origin main
```

- [ ] **Step 3: Tag v0.6.0 and push the tag**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git tag -a v0.6.0 -m "v0.6.0 — garden-prune (Delete/Archive). CRUD complete."
git push origin v0.6.0
```

- [ ] **Step 4: Verify**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git ls-remote --tags origin | grep v0.6.0
```

Expected: a single line showing `v0.6.0` resolved on the remote.

---

## Post-implementation notes (for the implementer)

- **Do not** test the new skill against the live vault in this same Claude Code session. The user does the user-side install loop themselves (`/plugin marketplace update knowledge-gardener` → `/reload-plugins`) before the skill is consumable, and third-party plugin `autoUpdate` is broken (issue #26744), so this is a manual hand-off.
- Versioning Discipline forbids `--no-verify`. If a pre-commit hook fails, investigate and fix in a follow-up step within the same task — do not bypass.
- `check-skill-refs.sh` greps the *entire* tree for `knowledge-gardener:[a-z][a-z0-9-]*`. Literal occurrences inside prose, code blocks, or quoted examples all count. The garden-connect spec lesson learned: reference siblings as bare names (`garden-water`) in your prose, and only use `knowledge-gardener:` when the directory exists.
- The README + CLAUDE.md edits are stylistically minor but politically important — once CRUD is complete the "Planned" footnote should disappear everywhere so the docs accurately advertise the surface area.
