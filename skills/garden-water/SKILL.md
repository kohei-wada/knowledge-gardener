---
name: garden-water
description: Use when an existing vault note needs new information, an added link, refined wording, or a metadata fix (tag / frontmatter field). Operates as a minimal diff on the existing note, never a wholesale rewrite. Pairs with garden-plant (new note) and garden-prune (removal).
---

# Garden Water (Update)

Water existing knowledge in the user's vault — append new info, add a link, fix a missing tag, refine wording. Operates as a **minimal diff** on a specific note; the vault's README still owns format conventions, this skill only owns the decision to touch existing content.

## When to Use

- User asks: "X に追記" / "<note> に Y を足して" / "<note> に `tool/ssh` タグ追加" / "update <note> with Y"
- Internal: `garden-plant` duplicate check found an existing close note → route here instead of creating a duplicate
- Internal: `garden-survey` surfaced a gap (e.g. missing tag, MOC link omission, broken cross-reference) → propose a targeted patch
- A note's frontmatter is wrong or incomplete and needs fixing

## When NOT to Use

- A new atomic insight with no close existing note → `garden-plant`
- Removing or archiving a note → `garden-prune`
- Just adding a graph edge between an existing MOC and an existing child note → `garden-connect`. If the link is part of a substantive content change (e.g. a new bullet under "Related Notes" that has explanatory text, or a link between two non-MOC notes), prefer this skill.
- Just searching → `garden-survey`
- The user wants to rewrite most of the note → that's a re-plant; stop and ask whether to start over rather than turning water into a rewrite

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
4. The target note's folder-scoped `README.md` if it exists

Extract: link syntax (e.g. standard markdown `[text](path.md)` vs `[[wikilink]]`), frontmatter schema, tag namespace, lint rules, commit conventions.

### Step 3: Identify Target Note(s)

- **Explicit path or filename in the request**: use it. Verify the file exists; if not, suggest `garden-plant`.
- **Topic only**: call `garden-survey` for candidates and present the top matches. **Ask** which to update — never silently pick.
- **Same logical change on multiple notes** (e.g. adding the same tag to several files): allowed in one invocation as long as the change is identical per file. Otherwise split into separate water operations.

### Step 4: Determine Change Type

| Change type | What it does | How to apply |
|-------------|--------------|--------------|
| **Append content** | Add a bullet, paragraph, or section to existing body | Edit: anchor on the section header or trailing fence, insert |
| **Modify content** | Rewrite a specific bullet, sentence, or section | Edit: old_string → new_string for that block |
| **Metadata** | Add / change a frontmatter field (e.g. tag, alias, date) | Edit on the YAML block at the top |
| **Add a link** | New `[text](rel/path.md)` inside an existing section | Edit, anchored on the section |

Pick **one** change type per invocation. Bundling tag-fix + section-addition in one commit hides intent. Split into separate water calls so the commit history stays atomic.

### Step 5: Read the Target

Read the existing note in full **using the Read tool** before drafting. The Edit tool tracks per-file Read history and will refuse to apply edits to a file that was never opened with `Read`; reading via `Bash` (`cat`, `head`, `grep` etc.) does **not** count for this tracking. So even if you already inspected the file via shell to scope the change, run `Read` on the file before the Edit step.

You need to know:

- Exact existing whitespace, indent, and bullet style (the Edit tool requires byte-exact match on `old_string`).
- Whether the section you're appending to already exists, and where its boundary is (next `## ` heading or EOF).
- The existing tag list (don't duplicate when adding a tag).
- The link syntax in use (avoid mixing wikilinks with standard markdown if the README forbids).

### Step 6: Draft the Change

Compose **only the diff**, not the whole file. The body of the change should:

- Match the note's tone and indent. Don't normalize 4-space indents to 2-space unless markdownlint will autofix them anyway.
- Use the vault's link syntax (per README — usually standard markdown, no URL encoding even for spaces).
- For frontmatter changes: insert the new line in the right list, preserve YAML indentation, never break the closing `---` fence.
- For new sections: use the existing heading depth and emoji style (e.g. `## 🔗 Related Links` when the note uses emoji'd headings).

### Step 7: Propose, Don't Commit

**Default: do not write directly.** Show the user:

1. The target file (absolute or `$KG_VAULT`-relative path).
2. The **diff** — before/after of just the changed lines, not the full file.
3. A one-line rationale: "Updating because <user request | survey gap | duplicate found via plant>."

Ask for approval. Apply only after the user confirms.

**Exception**: if the user explicitly said "update X" / "X に Y 足して" / "X 直して", treat that as approval. Still show the diff and path in the response so they can correct.

### Step 8: Apply the Change

Use the **Edit tool** (not Write — Edit preserves the rest of the file byte-for-byte). Provide a unique `old_string` anchor; if uniqueness is fragile, include enough surrounding context to disambiguate.

For frontmatter tag append, a typical anchor is the closing of the tags block:

```
old_string: "tags:\n  - moc\n  - idea\n  - tool/ssh\n"   # if you know exact existing tags
# or:
old_string: "tags:\n  - moc\n"                            # anchored at first tag, then re-list
```

Prefer the smallest unique anchor.

### Step 9: Lint and Commit

Per the vault's Versioning Discipline (declared in `$KG_VAULT/../CLAUDE.md` when present):

1. `pre-commit run --files <changed file>` — fix any lint or link issues it surfaces. Do not bypass with `--no-verify`.
2. `git add <changed file>` — stage only this file.
3. `git commit -m "water: <short subject>"` — subject describes the affected note and what changed.
4. `git push` to the configured remote.

### Commit Subject Examples

| Operation | Commit subject |
|-----------|----------------|
| Add a tag | `water: tag tool/ssh on ssh-key-management` |
| Add a link in a MOC | `water: ssh-MOC link to ssh設定の説明` |
| Refine a paragraph | `water: clarify ssh-port-forwarding "reverse" example` |
| Fix broken outgoing link | `water: fix link target in rsync-MOC` |
| Add a section | `water: add Related Links section to garden-water` |

Keep the subject under ~60 chars; put detail in the commit body if needed.

## Edge Cases

- **Target note not found**: do not silently create it. Suggest `garden-plant` instead, and surface the survey results so the user can confirm there's truly no close existing note.
- **Change duplicates existing content** (e.g. tag already present, identical bullet already in section): say so, don't write a no-op edit.
- **Pre-commit fails** (lint, broken link, markdownlint reformat): apply the fix the hook suggests, re-stage, retry. If pre-commit auto-reformats your diff (e.g. nested list indent), re-read the file and confirm the change is still what you intended before committing.
- **Frontmatter is malformed in the existing note** (broken YAML, missing closing `---`): stop and propose a frontmatter-only fix first as a separate water; don't pile your update on top of a broken header.
- **Multiple notes match the topic and the change is not identical per note**: split into separate water invocations so each commit stays atomic.
- **Edit anchor not unique**: expand the `old_string` with more surrounding context until unique, or pick a different anchor closer to the change.

## Key Principles

- **Minimal diff.** Touch only what needs touching. The rest of the note is sacred.
- **One logical change per commit.** Don't bundle a tag fix and a section addition; split into two water calls.
- **Preserve voice.** Match the note's tone, indent, link syntax, and section structure. Do not normalize on a whim.
- **Format from vault, never from this skill.** If you find yourself converting wikilinks to standard markdown unilaterally, that's a separate refactor — propose it explicitly, don't sneak it in.
- **Cite the trigger.** Internally know whether this change came from the user, a survey gap, or a plant duplicate-route. Use that to write a meaningful commit subject.
- **Never bypass lint.** Lint failures committed in are technical debt the next reader inherits.
- **Read-then-edit, not blind-write.** Always read the current state before drafting the diff. Don't trust your memory of what the file said earlier in the conversation.
