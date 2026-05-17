# garden-connect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `garden-connect` skill (the Link operation of CRUD) as knowledge-gardener v0.5.0. Scope is MOC ↔ child note linking only; bi-directional by default, uni-fallback when the child has no Related section.

**Architecture:** Pure skill-library plugin — no code, no tests in the traditional sense. Deliverable is a new `skills/garden-connect/SKILL.md` plus cross-skill doc updates (using-knowledge-gardener routing, garden-water boundary clarification, top-level README + CLAUDE.md skill tables, version bump). Pre-commit hooks (`check-skill-refs`, `check-skill-frontmatter`, `check-version-sync`) serve as the test suite.

**Tech Stack:** Markdown + YAML frontmatter, bash pre-commit scripts, git for atomic commits per the vault's Versioning Discipline.

**Source spec:** `docs/specs/2026-05-17-garden-connect-design.md`

**Working directory:** `~/ghq/github.com/Kohei-Wada/knowledge-gardener`

---

## File Structure

| Path | Action | Responsibility |
|------|--------|----------------|
| `skills/garden-connect/SKILL.md` | Create | The new skill's behavior, identical structural shape to `skills/garden-water/SKILL.md` |
| `skills/using-knowledge-gardener/SKILL.md` | Modify | Add garden-connect to Available Skills table + Skill Routing block; remove the "planned" footnote line |
| `skills/garden-water/SKILL.md` | Modify | Drop the "(when shipped)" qualifier on the existing garden-connect mention |
| `README.md` | Modify | Flip `garden-connect` row from `(planned)` to `(implemented)` in the Skills table |
| `CLAUDE.md` | Modify | Catch up the stale Skills table (currently only lists plant); add connect; rewrite the Planned line |
| `package.json` | Modify | `version: "0.4.0"` → `"0.5.0"` |
| `.claude-plugin/plugin.json` | Modify | `version: "0.4.0"` → `"0.5.0"` |
| `.claude-plugin/marketplace.json` | Modify | `plugins[0].version: "0.4.0"` → `"0.5.0"` |

**Commit discipline (mandatory per `CLAUDE.md` Versioning Discipline):**
- One logical change per commit. Pre-commit must pass; never `--no-verify`.
- Each commit is `git add <specific files>` then `git commit -m "..."`. No `git add -A`.
- The 3 version files (`package.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) MUST move together in a single commit — the `check-version-sync` hook fails otherwise.
- Tag `v0.5.0` is applied after the version-bump commit lands and is pushed separately (`git push --tags`).

**Commit order matters:** Task 1 creates the new skill directory first so that pre-commit's `check-skill-refs.sh` (which validates every `knowledge-gardener:xxx` mention against existing `skills/*/`) does not fail when Task 2 adds the cross-skill references.

---

### Task 1: Create the garden-connect skill

**Files:**
- Create: `skills/garden-connect/SKILL.md`

- [ ] **Step 1: Run pre-commit baseline to confirm clean tree**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git status --short
```
Expected: clean working tree (only the design spec committed in `635165f`).

- [ ] **Step 2: Create the skill file**

Write `skills/garden-connect/SKILL.md` with the following exact content:

````markdown
---
name: garden-connect
description: Use when an existing MOC and an existing child note need to be linked (bullet under the right MOC sub-heading, optionally a reciprocal back-link from the child). Atomic graph-edge insertion only — no surrounding prose, no section creation. Pairs with garden-water (content edits) and garden-plant (new notes).
---

# Garden Connect (Link)

Add a graph edge between a **MOC** and one or more **child notes**. Bi-directional by default. The vault's README still owns format conventions (link syntax, MOC convention); this skill only owns the decision to insert exactly one link line per touched file.

## When to Use

- User asks: "MOC に X を追加して" / "ssh-MOC と ssh-key-management を link して" / "connect <child> to <MOC>" / "link these N notes under <MOC>"
- Internal: `garden-survey` surfaced an orphan child note that should be indexed under its MOC → propose a connect
- Internal: `garden-plant` just created a child note that belongs under an existing MOC → propose a connect as the follow-up

## When NOT to Use

- The link comes with surrounding explanatory prose (a paragraph that contains the link, not a bare bullet) → `garden-water`
- The link is between two non-MOC notes → `garden-water`
- The child note has no Related/MOC section and the user wants bi-directional → first run `garden-water` to add the section, then run this skill
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

Confirm the named "MOC" is actually a MOC per the vault README's convention (any of: filename suffix like `-MOC.md`, frontmatter tag like `moc`, dedicated folder like `02_MOCs/`). If the file does not match the convention, stop and ask — do not treat an arbitrary note as a MOC, because then the operation is just a note-to-note link and belongs in `garden-water`.

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
3. If none match, downgrade to uni-directional per Step 5.

### Step 7: Read Every Target File With the Read Tool

The Edit tool tracks per-file Read history and will refuse to edit a file that was never opened with `Read`. Reading via `Bash` (`cat`, `head`, `grep`) does **not** count. So even if you inspected files via shell while scoping, run `Read` on each file (MOC + every touched child) before the Edit step.

You need to know:

- Exact existing whitespace, indent, and bullet style. The Edit tool requires byte-exact matches on `old_string`.
- The boundary of the chosen section (the next `## ` heading or EOF) so the new bullet lands inside it.
- Whether the target link is already present (skip as no-op; do not duplicate).
- The link syntax in use (do not mix wikilinks with standard markdown if the README forbids).

### Step 8: Draft the Diff

Compose only the new bullet(s) — one line per touched file. The bullet shape should:

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

| Operation | Subject |
|-----------|---------|
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
````

- [ ] **Step 3: Run pre-commit on the new file**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/garden-connect/SKILL.md
pre-commit run --files skills/garden-connect/SKILL.md
```

Expected: all hooks pass. In particular:
- `check-skill-frontmatter`: PASS (the file has `name:` and `description:`).
- `check-skill-refs`: PASS (the new file references `garden-water`, `garden-plant`, `garden-survey`, `garden-prune`; the first three exist as skill dirs, and `garden-prune` is referenced with `(when shipped)` qualifier as plain English, not a `knowledge-gardener:garden-prune` literal token).
- `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`: PASS.

If `check-skill-refs` fails because the SKILL.md uses the literal token `knowledge-gardener:garden-prune` anywhere, re-read the file and convert that mention to plain English (`garden-prune` without the namespace prefix), then re-stage and retry.

- [ ] **Step 4: Commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git commit -m "feat: garden-connect skill — MOC ↔ child linking primitive

Atomic graph-edge insertion only: bullet under the right MOC sub-heading,
optionally a reciprocal back-link from the child. Generic note-to-note
linking and link-with-prose stay in garden-water. Bi-directional by default,
uni-fallback when the child has no Related section."
```

Expected: commit succeeds, pre-commit passes, single file added.

---

### Task 2: Route garden-connect from using-knowledge-gardener

**Files:**
- Modify: `skills/using-knowledge-gardener/SKILL.md`

- [ ] **Step 1: Add the row to the Available Skills table**

Use the Edit tool. `old_string`:

```
| `knowledge-gardener:garden-water` | Update an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits, never wholesale rewrites |
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |
```

`new_string`:

```
| `knowledge-gardener:garden-water` | Update an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits, never wholesale rewrites |
| `knowledge-gardener:garden-connect` | Link an existing MOC and an existing child note (atomic graph-edge insertion, bi-directional by default) |
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |
```

- [ ] **Step 2: Add routing entries**

Use the Edit tool. `old_string`:

```
(internal — garden-survey surfaced a gap like missing tag or broken MOC link)
  → garden-water (propose the patch, ask before applying)

"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap
```

`new_string`:

```
(internal — garden-survey surfaced a gap like missing tag or broken MOC link)
  → garden-water (propose the patch, ask before applying)

"MOC に X を追加して" / "<MOC> と <child> を link して" / "connect <child> to <MOC>"
  → garden-connect

(internal — garden-survey surfaced an orphan note that should be indexed under a MOC)
  → garden-connect

(internal — garden-plant created a child that belongs under an existing MOC)
  → garden-connect (propose as follow-up to the new note)

"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap
```

- [ ] **Step 3: Drop the "planned" footnote**

Use the Edit tool. `old_string`:

```
(More CRUD skills — `garden-connect` (link), `garden-prune` (delete/archive) — are planned and will appear here as they ship.)
```

`new_string`:

```
(One more CRUD skill — `garden-prune` (delete/archive) — is planned and will appear here as it ships.)
```

- [ ] **Step 4: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/using-knowledge-gardener/SKILL.md
pre-commit run --files skills/using-knowledge-gardener/SKILL.md
git commit -m "docs(using-kg): route garden-connect (table + routing block)"
```

Expected: pre-commit passes (`check-skill-refs` now finds the new `knowledge-gardener:garden-connect` references and resolves them against the `skills/garden-connect/` dir created in Task 1).

---

### Task 3: Drop "(when shipped)" qualifier in garden-water

**Files:**
- Modify: `skills/garden-water/SKILL.md:21`

- [ ] **Step 1: Patch the qualifier**

Use the Edit tool. `old_string`:

```
- Just adding a graph edge between two existing notes that don't change otherwise → `garden-connect` (when shipped). If the link is part of a substantive content change (e.g. a new bullet under "Related Notes" that has explanatory text), prefer this skill.
```

`new_string`:

```
- Just adding a graph edge between an existing MOC and an existing child note → `garden-connect`. If the link is part of a substantive content change (e.g. a new bullet under "Related Notes" that has explanatory text, or a link between two non-MOC notes), prefer this skill.
```

This both removes the "(when shipped)" qualifier and tightens the description to match garden-connect's actual MOC-only scope.

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add skills/garden-water/SKILL.md
pre-commit run --files skills/garden-water/SKILL.md
git commit -m "docs(water): garden-connect is shipped and is MOC ↔ child only"
```

---

### Task 4: Update top-level README skill table

**Files:**
- Modify: `README.md:73`

- [ ] **Step 1: Flip the garden-connect row from planned to implemented**

Use the Edit tool. `old_string`:

```
| `garden-connect` | **(planned)** Add links between related notes |
```

`new_string`:

```
| `garden-connect` | **(implemented)** Link an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
```

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add README.md
pre-commit run --files README.md
git commit -m "docs(readme): mark garden-connect as implemented"
```

---

### Task 5: Update CLAUDE.md skill table

The `CLAUDE.md` Skills table is stale — it only lists `using-knowledge-gardener` and `garden-plant`. This catches it up in one go (water, survey, recap, connect all added; planned line rewritten).

**Files:**
- Modify: `CLAUDE.md:18-23`

- [ ] **Step 1: Replace the Skills section**

Use the Edit tool. `old_string`:

```
## Skills

| Skill | Purpose |
|-------|---------|
| using-knowledge-gardener | Entry point — routes requests to operational skills, declares variables and the format contract |
| garden-plant | Captures a new durable insight as a vault note, using conventions read from the vault's README |

Planned (not yet shipped): `garden-water` (update), `garden-connect` (link), `garden-prune` (delete/archive), `garden-survey` (read/search).
```

`new_string`:

```
## Skills

| Skill | Purpose |
|-------|---------|
| using-knowledge-gardener | Entry point — routes requests to operational skills, declares variables and the format contract |
| garden-plant | Captures a new durable insight as a vault note, using conventions read from the vault's README |
| garden-survey | Read-only search/listing primitive (text, tag, frontmatter, folder). Used directly and by other skills |
| garden-water | Updates an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits |
| garden-connect | Links an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
| garden-recap | Wraps up a session by writing what was worked on to today's daily note, so the next session can pick up context |

Planned (not yet shipped): `garden-prune` (delete/archive).
```

- [ ] **Step 2: Run pre-commit and commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add CLAUDE.md
pre-commit run --files CLAUDE.md
git commit -m "docs(claude): catch up Skills table (water/survey/recap/connect)"
```

---

### Task 6: Bump version to 0.5.0

The 3 version files must move atomically — the `check-version-sync` hook fails on any mismatch.

**Files:**
- Modify: `package.json`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Bump package.json**

Use the Edit tool. `old_string`:

```
  "version": "0.4.0",
  "type": "module"
```

`new_string`:

```
  "version": "0.5.0",
  "type": "module"
```

- [ ] **Step 2: Bump .claude-plugin/plugin.json**

Use the Edit tool. `old_string`:

```
  "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
  "version": "0.4.0",
```

`new_string`:

```
  "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
  "version": "0.5.0",
```

- [ ] **Step 3: Bump .claude-plugin/marketplace.json**

Use the Edit tool. `old_string`:

```
      "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
      "version": "0.4.0",
```

`new_string`:

```
      "description": "Format-agnostic knowledge-base curation skill. Decides WHEN to capture, update, link, or prune long-term knowledge — defers HOW (format/conventions) to the vault's own README.",
      "version": "0.5.0",
```

- [ ] **Step 4: Run pre-commit on the 3 version files**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
pre-commit run --files package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
```

Expected: `check-version-sync` PASS (all three read `0.5.0` now). If it fails, one of the Edits did not land — re-Read the failing file and patch.

- [ ] **Step 5: Commit**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git commit -m "chore: bump version to 0.5.0 (garden-connect)"
```

---

### Task 7: Push and tag v0.5.0

- [ ] **Step 1: Sanity check the commit graph**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git log --oneline -8
```

Expected (most recent first):

```
<hash> chore: bump version to 0.5.0 (garden-connect)
<hash> docs(claude): catch up Skills table (water/survey/recap/connect)
<hash> docs(readme): mark garden-connect as implemented
<hash> docs(water): garden-connect is shipped and is MOC ↔ child only
<hash> docs(using-kg): route garden-connect (table + routing block)
<hash> feat: garden-connect skill — MOC ↔ child linking primitive
635165f docs(connect): design spec for garden-connect (v0.5.0)
b1fbf64 feat: garden-recap skill — wrap up a session into today's daily note
```

If any commit is out of order or missing, stop and fix before pushing or tagging.

- [ ] **Step 2: Push commits**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git push origin main
```

- [ ] **Step 3: Tag v0.5.0 and push the tag**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git tag -a v0.5.0 -m "v0.5.0 — garden-connect (Link)"
git push origin v0.5.0
```

- [ ] **Step 4: Verify**

```bash
cd ~/ghq/github.com/Kohei-Wada/knowledge-gardener
git ls-remote --tags origin | grep v0.5.0
```

Expected: a single line showing `v0.5.0` resolved on the remote.

---

## Post-implementation notes (for the implementer)

- **Do not** test the new skill against the live vault in this same Claude Code session. The user does the user-side install loop themselves (`/plugin marketplace update knowledge-gardener` → `/reload-plugins`) before the skill is consumable, and third-party plugin `autoUpdate` is broken (issue #26744), so this is a manual hand-off.
- The CLAUDE.md catch-up in Task 5 fixes pre-existing staleness in addition to adding garden-connect; the commit message is honest about this.
- Versioning Discipline forbids `--no-verify`. If a pre-commit hook fails, investigate and fix in a follow-up step within the same task — do not bypass.
