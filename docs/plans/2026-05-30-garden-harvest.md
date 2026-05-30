# garden-harvest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `garden-harvest` skill — a stateless pipe that turns vault knowledge into a published blog post, owning orchestration only and resolving every convention from a README entry point.

**Architecture:** A markdown SKILL.md (no Python). It references the shared Pre-flight Setup / Common Workflow Steps in `using-knowledge-gardener`, reads the **vault README** for the gather convention and the **blog repo README** (located via `KG_BLOG_REPO`) for emit/mask conventions, runs a propose-then-confirm dialogue, and commits the post into the blog repo (no push). It is wired into the entry skill's Available Skills table, Skill Routing, and Variables, and documented in README + CLAUDE.md.

**Tech Stack:** Claude Code skill library (markdown SKILL.md + YAML frontmatter); validation via the repo's pre-commit hooks (`SKILL.md frontmatter`, `check-skill-refs`, markdownlint, version-match). No pytest — these skills have no unit tests.

**Spec:** [docs/specs/2026-05-30-garden-harvest-design.md](../specs/2026-05-30-garden-harvest-design.md)

---

## File Structure

- **Create** `skills/garden-harvest/SKILL.md` — the skill itself (frontmatter + process). Single responsibility: orchestrate the vault→blog pipe.
- **Modify** `skills/using-knowledge-gardener/SKILL.md` — Available Skills table (+1 row), CRUD summary line, Skill Routing (+1 block), Variables (+`KG_BLOG_REPO`).
- **Modify** `README.md` — skills table (+1 row) and env documentation (+`KG_BLOG_REPO` near `KG_VAULT`).
- **Modify** `CLAUDE.md` — the maintainer "Operational skills" enumeration (line ~25).
- **Modify** `package.json` + `.claude-plugin/plugin.json` — version bump `0.18.0` → `0.19.0`.

There is no `marketplace.json` in this repo; the version-match hook covers `package.json` + `plugin.json` only.

---

## Task 1: Author the garden-harvest SKILL.md

**Files:**
- Create: `skills/garden-harvest/SKILL.md`

- [ ] **Step 1: Write the SKILL.md**

Create `skills/garden-harvest/SKILL.md` with exactly this content:

````markdown
---
name: garden-harvest
description: Use when the user wants to turn vault knowledge into a published blog post — gathers the relevant permanent notes, shapes the post in a dialogue (no stored draft), masks PII, and emits it into the blog repo per that repo's own conventions. Triggers on "blog 化して", "記事化して", "publish this as a post", "ブログにして", "harvest these notes into a post".
---

# Garden Harvest (Knowledge → Blog Post)

Turn mature vault knowledge into a published blog post. `garden-harvest` is the "take it out into the world" verb — the counterpart to `garden-plant` (capture). It is a **stateless pipe**:

```
vault (knowledge, source of truth)
  ──[gather: declared by the VAULT README]──▶ dialogue (shape the post with you)
  ──[emit + mask: declared by the BLOG repo README]──▶ blog repo (the published artifact)
```

It owns **WHEN / orchestration only** and hardcodes no format. The in-progress draft is the **conversation**, never a file — nothing is stored in the vault, the blog repo (until commit), or a cache.

## When to Use

- "この話を blog 化して" / "記事化して" / "publish this as a post" / "ブログにして"
- A topic has matured across several permanent notes and is worth publishing.
- Pairs with `garden-survey` to find publish-worthy permanent notes first.

## When NOT to Use

- Capturing a new insight into the vault → `garden-plant`.
- Updating an existing note → `garden-water`.
- Just searching/listing → `garden-survey`.
- The material is a generic explainer with no first-hand layer — it will fail the blog's worth-publishing test; don't start the pipe.

## Process

Propose-then-confirm throughout, matching the other write skills.

### Step 1: Pre-flight — vault side

Follow [Pre-flight Setup](../using-knowledge-gardener/SKILL.md#pre-flight-setup-shared-by-all-operational-skills) to resolve `$KG_VAULT` and load vault conventions. From the conventions, extract the **gather convention** the vault README declares for blog material (for a Zettelkasten vault: *bundle the relevant permanent notes and the notes they link to*).

If the vault README declares no gather convention for blog material, **stop and ask** — do not invent one.

### Step 2: Pre-flight — blog side

1. Resolve `KG_BLOG_REPO` (a local path to the blog repo clone). If unset, stop and report: "Set `KG_BLOG_REPO` to your blog repo root (e.g. `export KG_BLOG_REPO=~/src/blog`) and restart the session." If the path does not exist, stop and report it.
2. Read `$KG_BLOG_REPO/README.md` and follow the pointer it declares to the post-writing conventions doc. **Do not hardcode a path** (e.g. `docs/content-creation.md`) — discover it from the README. Read that doc.
3. From it, extract whatever the emit step needs: post format, frontmatter schema, the **worth-publishing test**, the **PII-masking rules**, and any structural requirement (e.g. locale parity). The skill does not know these a priori.
4. If the blog README declares no pointer to write/mask conventions, **stop and ask** — do not invent them.

### Step 3: Gather

Following the vault's gather convention, assemble the relevant permanent notes (and the notes they link to) for the topic as raw material. Read the **real-valued** notes directly — they are visible to you during the dialogue. Write nothing to the vault.

### Step 4: Dialogue

Shape the post with the user — angle, structure, what first-hand experience it carries. The draft *is* this conversation; create no draft file anywhere.

Apply the blog's **worth-publishing test** as a gate: if the candidate carries no experiment / failure / judgment / first-hand layer, say so and stop without publishing. There is no "rejected" artifact to file — the outcome is simply not to emit.

### Step 5: Emit + mask

Produce the post per the blog repo's resolved conventions, satisfying every structural requirement they declare (e.g. locale parity) and applying their **PII-masking rules** to the emitted copy — the source notes keep the real values; only the public copy is masked.

Follow [Common: Propose, Don't Commit](../using-knowledge-gardener/SKILL.md#common-propose-dont-commit): show the target path(s) under `$KG_BLOG_REPO`, the full draft of each file, a one-line rationale, and an explicit **masking confirmation** (what real values were redacted to what). Apply only after the user confirms.

### Step 6: Commit (not push)

In the blog repo, run the repo's documented verify/lint steps, then **commit** the post file(s). **Stop at commit — do not push.** Push triggers deployment and stays a manual user action; say so.

This mirrors [Common: Lint, Commit, Push](../using-knowledge-gardener/SKILL.md#common-lint-commit-push) except the target is the **blog repo** (not the vault) and the sequence ends before push. Use a commit subject in the blog repo's own convention (the conventions doc declares it).

## State

- **No persistent draft** — not in the vault, the blog repo, or a state dir.
- **No cache.** Each invocation re-gathers from the vault.
````

- [ ] **Step 2: Verify the frontmatter hook passes**

Run: `pre-commit run --files skills/garden-harvest/SKILL.md`
Expected: `SKILL.md has required name + description frontmatter` → Passed; markdownlint → Passed. (The `check-skill-refs` hook only checks `knowledge-gardener:<skill>` mentions; this file's relative links are fine.)

- [ ] **Step 3: Commit**

All commands below run from the knowledge-gardener repo root.

```bash
git add skills/garden-harvest/SKILL.md
git commit -m "feat(garden-harvest): add vault→blog pipe skill (#29)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire garden-harvest into using-knowledge-gardener

**Files:**
- Modify: `skills/using-knowledge-gardener/SKILL.md`

- [ ] **Step 1: Add a row to the Available Skills table**

Find this line (the last row, garden-recap):

```markdown
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |
```

Add immediately after it:

```markdown
| `knowledge-gardener:garden-harvest` | Turn mature vault knowledge into a published blog post — gather the relevant permanent notes, shape the post in dialogue (no stored draft), mask PII, emit into the blog repo per that repo's conventions |
```

- [ ] **Step 2: Update the CRUD summary line**

Find:

```markdown
CRUD is complete: garden-plant (C), garden-survey (R), garden-water (U), garden-prune (D). garden-connect adds the link primitive; garden-recap handles session wrap-up.
```

Replace with:

```markdown
CRUD is complete: garden-plant (C), garden-survey (R), garden-water (U), garden-prune (D). garden-connect adds the link primitive; garden-recap handles session wrap-up; garden-harvest publishes knowledge out to the blog repo.
```

- [ ] **Step 3: Add a Skill Routing block**

Find the last routing block (garden-recap):

```markdown
"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap
```

Add immediately after it (still inside the code fence):

```markdown

"blog 化して" / "記事化して" / "publish this as a post" / "ブログにして"
  → garden-harvest

(internal — garden-survey surfaced a cluster of permanent notes worth publishing)
  → garden-harvest (propose; gather from the vault, emit into the blog repo, never store a draft)
```

- [ ] **Step 4: Add KG_BLOG_REPO to the Variables section**

Find:

```markdown
- `KG_VAULT` = value of the `KG_VAULT` environment variable. If unset, skills MUST stop and tell the user: "Set `KG_VAULT` to your vault root (e.g. `export KG_VAULT=~/notes`) and restart the session."
```

Add immediately after it:

```markdown
- `KG_BLOG_REPO` = value of the `KG_BLOG_REPO` environment variable — a local path to the blog repo clone, used only by `garden-harvest`. If unset (or the path does not exist), `garden-harvest` MUST stop and tell the user: "Set `KG_BLOG_REPO` to your blog repo root (e.g. `export KG_BLOG_REPO=~/src/blog`) and restart the session." Other skills do not use it.
```

- [ ] **Step 5: Verify reference + lint hooks pass**

Run: `pre-commit run --files skills/using-knowledge-gardener/SKILL.md`
Expected: `check-skill-refs` → Passed (garden-harvest now exists); markdownlint → Passed.

- [ ] **Step 6: Commit**

```bash
git add skills/using-knowledge-gardener/SKILL.md
git commit -m "feat(garden-harvest): route from using-knowledge-gardener + declare KG_BLOG_REPO

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Update README + CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add garden-harvest to the README skills table**

Find:

```markdown
| `garden-prune` | **(implemented)** Remove a named note — archive by default (git mv into the vault's archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; cleanup goes through garden-water |
```

Add immediately after it:

```markdown
| `garden-harvest` | **(implemented)** Turn mature vault knowledge into a published blog post — gather permanent notes, shape in dialogue (no stored draft), mask PII, emit into the blog repo (`KG_BLOG_REPO`) per that repo's conventions; commits, never pushes |
```

- [ ] **Step 2: Document KG_BLOG_REPO in the README env section**

Find (near line 30):

```markdown
export KG_VAULT=~/path/to/your/vault
```

Add immediately after that line (inside the same code block):

```markdown
export KG_BLOG_REPO=~/path/to/your/blog/repo   # only needed for garden-harvest
```

- [ ] **Step 3: Update the CLAUDE.md operational-skills enumeration**

Find:

```markdown
- Operational skills: `garden-plant` (C), `garden-survey` (R), `garden-water` (U), `garden-prune` (D), plus `garden-connect` (link edges) and `garden-recap` (session wrap-up).
```

Replace with:

```markdown
- Operational skills: `garden-plant` (C), `garden-survey` (R), `garden-water` (U), `garden-prune` (D), plus `garden-connect` (link edges), `garden-recap` (session wrap-up), and `garden-harvest` (publish knowledge into the blog repo via `KG_BLOG_REPO`; commit-not-push).
```

- [ ] **Step 4: Verify lint passes**

Run: `pre-commit run --files README.md CLAUDE.md`
Expected: markdownlint → Passed; link check (if configured) → Passed.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: list garden-harvest in README + CLAUDE.md, document KG_BLOG_REPO

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Version bump + full verification

**Files:**
- Modify: `package.json`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump the version in both files**

In `package.json` and `.claude-plugin/plugin.json`, change:

```json
  "version": "0.18.0",
```

to:

```json
  "version": "0.19.0",
```

- [ ] **Step 2: Run the full pre-commit suite**

Run: `pre-commit run --all-files`
Expected: all hooks Passed — in particular `versions match across package.json, plugin.json, marketplace.json`, `SKILL.md has required name + description frontmatter`, and `check-skill-refs`.

- [ ] **Step 3: Manually verify the skill triggers (feature correctness)**

In a Claude Code session with this plugin loaded and `KG_BLOG_REPO` set, type a trigger phrase (e.g. "この話を blog 化して"). Confirm the assistant routes to `garden-harvest` (announces "Using garden-harvest …") and that, with `KG_BLOG_REPO` unset, it stops and asks for the env var rather than guessing a path. Record the observed behavior — do not claim success without seeing it.

- [ ] **Step 4: Commit**

```bash
git add package.json .claude-plugin/plugin.json
git commit -m "chore(release): bump 0.18.0 -> 0.19.0 (garden-harvest)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Push (only when the user asks)**

```bash
git push
```

---

## Self-Review notes

- **Spec coverage:** verb-first skill routed from entry (Task 1+2); gather from vault README + emit/mask from blog README pointer, nothing hardcoded (Task 1 Steps 1–2, 5); no durable draft / no v1 cache (Task 1 SKILL.md "State"); stop-and-ask on missing conventions (Task 1 Steps 1–2); propose/commit discipline targeting the blog repo, commit-not-push (Task 1 Step 6); `KG_BLOG_REPO` declared in Variables (Task 2 Step 4) and documented (Task 3). All spec acceptance items map to a task.
- **No marketplace.json:** the version-match hook covers package.json + plugin.json; both bumped in Task 4.
- **Trigger phrases** are consistent between the SKILL.md `description` (Task 1) and the routing block (Task 2 Step 3).
