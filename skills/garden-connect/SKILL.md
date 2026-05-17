---
name: garden-connect
description: Use when an existing MOC and an existing child note need to be linked (bullet under the right MOC sub-heading, optionally a reciprocal back-link from the child). Atomic graph-edge insertion only — no surrounding prose, no section creation. Pairs with garden-water (content edits) and garden-plant (new notes).
---

# Garden Connect (Link)

Add a graph edge between a **MOC** and one or more **child notes**. Bi-directional by default. The vault's README still owns format conventions (link syntax, MOC convention); this skill only owns the decision to insert bare link bullets — at most one per child file, one per child in the MOC's chosen section.

## When to Use

- User asks: "MOC に X を追加して" / "ssh-MOC と ssh-key-management を link して" / "connect <child> to <MOC>" / "link these N notes under <MOC>"
- Internal: `garden-survey` surfaced an orphan child note that should be indexed under its MOC → propose a connect
- Internal: `garden-plant` just created a child note that belongs under an existing MOC → propose a connect as the follow-up

## When NOT to Use

- The link comes with surrounding explanatory prose (a paragraph that contains the link, not a bare bullet) → `garden-water`
- The link is between two non-MOC notes → `garden-water`
- The child note has no existing Related/MOC section and the user wants bi-directional → first run `garden-water` to add the section, then run this skill
- Removing or rewriting an existing link → `garden-prune` (when shipped) for removal, `garden-water` for rewrite
- A new atomic insight with no existing note → `garden-plant`
- Just searching → `garden-survey`
- Semantically discovering what *should* be linked — out of scope. The caller (user or another skill) names the pair; this skill does not infer.

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

Extract: link syntax (e.g. standard markdown `[text](path.md)` vs `[[wikilink]]`), MOC convention (filename suffix, frontmatter tag, or folder), tag namespace, lint rules, commit conventions.

### Step 3: Identify MOC and Child(ren)

- **Explicit path or filename in the request**: use it. Verify each file exists; if not, suggest `garden-plant` for the missing one.
- **Topic only**: call `garden-survey` for candidates and ask which to use. Never silently pick.
- **Multiple children under the same MOC** (batch): allowed in one invocation as long as the change is identical in shape per child. Heterogeneous source/target combinations must be split into separate invocations.

### Step 4: Verify MOC-ness

Confirm the named "MOC" is actually a MOC per the vault README's convention (which may use a filename suffix, a frontmatter tag, a dedicated folder, or any combination). If the file does not match the convention, stop and ask — do not treat an arbitrary note as a MOC, because then the operation is just a note-to-note link and belongs in `garden-water`.

### Step 5: Decide Direction

Default: **bi-directional**. Add the link on both sides in the same commit.

Fall back to **uni-directional** (MOC → child only) when any of:

- The user explicitly asked for one-way ("片方向で" / "no back-link" / "MOC 側だけ").
- The child note has no existing Related / MOC / 関連 section to receive a back-link. Surface this and recommend `garden-water` as a follow-up to add the section if the user wants symmetry later.

Never create a Related section as part of this skill — that is `garden-water`'s job.

### Step 6: Locate Insertion Sections

**On the MOC side:**

1. Parse the MOC's `## ` and `### ` sub-headings.
2. Pick the heading whose topic best matches the child's tags and title.
3. Propose your choice with the reasoning ("Child has `tag/ssh`; suggest inserting under `## SSH 設定`").
4. If no heading is a clear match, list candidate headings and ask the user.
5. If the MOC has no sub-headings at all (flat bullet list), append at the end of the main body, before any trailing meta section like "## Related MOCs". Surface the structure choice in the proposal.

**On the child side (bi-directional only):**

1. Find an existing section that holds links to MOCs. Common variants in the wild: `## 関連`, `## 🔗 Related Links`, `## Related`, `## MOC`, `## MOCs`. Match by the vault's documented convention if any.
2. If multiple match, ask which.
3. If none match, fall back to uni-directional (as defined in Step 5) and proceed with only the MOC side.

### Step 7: Read Every Target File With the Read Tool

The Edit tool tracks per-file Read history and will refuse to edit a file that was never opened with `Read`. Reading via `Bash` (`cat`, `head`, `grep`) does **not** count. So even if you inspected files via shell while scoping, run `Read` on each file (MOC + every touched child) before the Edit step.

You need to know:

- Exact existing whitespace, indent, and bullet style. The Edit tool requires byte-exact matches on `old_string`.
- The boundary of the chosen section (the next `## ` heading or EOF) so the new bullet lands inside it.
- Whether the target link is already present (skip as no-op; do not duplicate).
- The link syntax in use (do not mix wikilinks with standard markdown if the README forbids).

### Step 8: Draft the Diff

Compose only the new bullet(s). Each child file receives one bullet; the MOC receives one bullet per child in the batch. The bullet shape should:

- Match the section's existing bullet style (e.g. `- [Display Text](path/to/file.md)` vs `* …`).
- Use the relative path from the touched file to the linked file (no URL encoding even for spaces, per typical vault README).
- For batch into a single MOC heading: stack the bullets in alphabetical order under the chosen heading unless the existing list is in an obvious different order (e.g. chronological), in which case match the existing order.

Skip any side where the link already exists. Report skipped sides in the proposal so the user knows the resulting state.

### Step 9: Propose, Don't Commit

**Default: do not write directly.** Show the user:

1. Each target file (absolute or `$KG_VAULT`-relative path).
2. The per-file **diff** — before/after of just the affected lines.
3. The direction (uni or bi) and a one-line rationale: "connect <child> ↔ <MOC>" or "connect N children ↔ <MOC>".
4. Any sides skipped because the link was already present.

Ask for approval. Apply only after the user confirms.

**Exception:** an explicit "connect X to Y" / "MOC に X を追加して" request counts as approval. Still show the diff and direction in the response so the user can correct.

### Step 10: Apply the Change

Use the **Edit tool** (not Write — Edit preserves the rest of each file byte-for-byte). For each file, provide a unique `old_string` anchor. If uniqueness is fragile, include enough surrounding context to disambiguate (typically the heading line of the target section, or the adjacent bullet).

### Step 11: Lint, Commit, Push

Per the vault's Versioning Discipline (declared in `$KG_VAULT/../CLAUDE.md` when present):

1. `pre-commit run --files <every changed file>` — fix any lint or link issues. Do not bypass with `--no-verify`.
2. `git add <every changed file>` — stage only the touched files.
3. `git commit -m "connect: <subject>"` — see the table below for the subject shape. One commit covers the whole logical link operation, even when it spans the MOC + multiple children.
4. `git push` to the configured remote.

### Commit Subject Examples

| Operation | Commit subject |
|-----------|----------------|
| Uni single (MOC → child) | `connect: ssh-MOC → ssh-key-management` |
| Bi single | `connect: ssh-port-forwarding ↔ ssh-MOC` |
| Batch into MOC (uni) | `connect: 4 ssh notes → ssh-MOC` |
| Bi batch | `connect: 4 ssh notes ↔ ssh-MOC` |

Cap at ~60 chars; put detail in the commit body when needed.

## Edge Cases

- **MOC not found or not actually a MOC** (per vault README convention): stop. Suggest `garden-plant` if the MOC should exist, or correct the target.
- **Child not found**: stop. Suggest `garden-plant`.
- **Both sides already have the link**: do nothing. Report it as a no-op.
- **One side already has the link, other doesn't**: edit only the missing side; report the skip.
- **Child has no Related/MOC section** under bi-directional request: fall back to uni-directional, recommend `garden-water` for adding the section as a separate follow-up.
- **No clear MOC heading match for the child**: ask the user, do not silently pick.
- **MOC has no sub-headings at all**: append at the end of the body, before any trailing meta section. Mention the structural choice in the proposal.
- **Pre-commit reformats the diff** (markdownlint normalises bullet indent, link checker rewrites a path): re-read the touched files, confirm the change is still what you intended, re-stage, retry.
- **Heterogeneous batch attempted** (different MOCs, or different bullet shapes per child): split into separate invocations. Do not collapse into one commit.

## Key Principles

- **One graph edge per logical change.** Bi-directional MOC ↔ child is one edge with two endpoints, so one commit. Multiple children under the same MOC is one batch operation, also one commit. A different MOC is a different operation, different commit.
- **Bullet only — no prose.** If the link needs explanation, escalate to `garden-water` and let it take ownership of the whole edit.
- **Section discovery, not section creation.** If the target section does not exist on the child side, fall back to uni-directional. Do not invent headings.
- **Format from vault, never from this skill.** Bullet style, link syntax, indent — copy from the file you are editing. Do not normalise on a whim.
- **Read-then-edit, not blind-write.** Always read every target file before drafting the diff. Memory from earlier in the conversation is not authoritative.
- **Never bypass lint.** Pre-commit failures committed in are technical debt the next reader inherits.
- **Cite the trigger.** Internally know whether this came from the user, from `garden-survey` finding an orphan, or from `garden-plant` proposing a follow-up. Use that to write a meaningful commit subject and rationale.
