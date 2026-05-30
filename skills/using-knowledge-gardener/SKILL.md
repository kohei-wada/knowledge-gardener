---
name: using-knowledge-gardener
description: Use when starting any conversation - establishes how to find and use long-term knowledge curation skills that read, write, link, and prune the user's external knowledge base
---

# Using knowledge-gardener

You have access to skills for tending the user's long-term knowledge base (the "vault"). These skills decide **when** to capture, update, link, or prune knowledge. They do **not** decide **how** — format and conventions are owned by the vault itself (see [Variables](#variables) and [The Format Contract](#the-format-contract)).

## Available Skills

| Skill | Use When |
|-------|----------|
| `knowledge-gardener:garden-plant` | A reusable insight, decision, or lesson surfaced in conversation that's worth keeping — capture it as a new note |
| `knowledge-gardener:garden-survey` | Search, list, or query the vault (by text, tag, frontmatter field, or folder) — read-only. Used directly by the user and internally by other skills as their lookup primitive |
| `knowledge-gardener:garden-water` | Update an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits, never wholesale rewrites |
| `knowledge-gardener:garden-connect` | Link an existing MOC and an existing child note (atomic graph-edge insertion, bi-directional by default) |
| `knowledge-gardener:garden-prune` | Remove an existing note — archive by default (git mv into the vault's archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; never auto-rewrites links |
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |
| `knowledge-gardener:garden-harvest` | Turn mature vault knowledge into a published blog post — gather the relevant permanent notes, shape the post in dialogue (no stored draft), mask PII, emit into the blog repo per that repo's conventions |

CRUD is complete: garden-plant (C), garden-survey (R), garden-water (U), garden-prune (D). garden-connect adds the link primitive; garden-recap handles session wrap-up; garden-harvest publishes knowledge out to the blog repo.

## The Format Contract

This plugin is **format-agnostic**. Skills MUST NOT hardcode note structure, filename rules, link syntax, frontmatter fields, folder layout, or any other formatting decision.

The vault is the source of truth for "how". This plugin is the source of truth for "when".

## Pre-flight Setup (shared by all operational skills)

Every operational skill (`garden-plant` / `garden-water` / `garden-survey` / `garden-connect` / `garden-prune` / `garden-recap`) begins with the same two pre-flight steps. They are defined **once here** and referenced from each skill instead of being copied. Skills extract different things from the conventions — that extraction list lives in the skill, not here.

### Step P1: Resolve Vault Path

1. Read `KG_VAULT` environment variable.
2. If unset: stop. Report: "Set `KG_VAULT` to your vault root (e.g. `export KG_VAULT=~/notes`) and restart the session."
3. Verify the directory exists. If not: stop and report the missing path.

Refer to the resolved path as `$KG_VAULT` throughout the skill.

### Step P2: Load Vault Conventions

Read these in order, stopping when you have enough to act:

1. **`$KG_VAULT/README.md`** — vault-root convention document (most specific).
2. **`$KG_VAULT/../README.md`** — parent directory README. Many vaults live as a subdirectory of a git repo (e.g. `Obsidian/vault/`); the repo-root README often holds the convention spec. Read both — the vault-root one overrides on conflict, the parent fills gaps.
3. **`$KG_VAULT/CLAUDE.md`** or **`$KG_VAULT/../CLAUDE.md`** if present — operational instructions including Versioning Discipline (lint/commit/push workflow).
4. **Folder-scoped `README.md`** — if the target folder has its own `README.md`, read it for sub-folder-specific rules.
5. Any style/structure doc the above explicitly point to (e.g. `CONVENTIONS.md`, `STRUCTURE.md`, `_meta/README.md`).
6. A representative existing note from the target folder — to see conventions in practice.

If a critical convention is unclear or absent, **stop and ask the user** rather than guess. Inventing a silent default is a failure mode.

What each skill needs to **extract** from the conventions (link syntax, frontmatter schema, archive folder, daily-note template, etc.) is skill-specific and listed at the top of the skill's process.

## Common Workflow Steps (shared by write skills)

Three workflow steps appear in every operational skill that mutates the vault. They are defined **once here** and referenced from each skill instead of being copied.

### Common: Read Every Target With the Read Tool

Before drafting any change, run the **Read tool** on every file you intend to Edit. The Edit tool tracks per-file Read history and will refuse to apply edits to a file that was never opened via Read; reading via Bash (`cat`, `head`, `grep`, etc.) does **not** count toward this tracking. Even if you already inspected the file in shell to scope the change, run Read on it before the Edit step.

What you need to come away with: exact existing whitespace, indent, and bullet style (Edit requires byte-exact match on `old_string`); section boundaries (next `## ` heading or EOF); the link syntax in use; and whether the change you're about to propose is already present (skip as no-op).

The skill's own "Read" step lists any skill-specific items beyond this baseline.

### Common: Propose, Don't Commit

**Default: do not write directly.** Show the user:

1. The target path(s) (absolute or `$KG_VAULT`-relative).
2. The full content (new file) or **diff** (edit), as appropriate.
3. A one-line rationale for the change.
4. Skill-specific extras as listed in the skill's own Propose step (e.g. direction for `garden-connect`, inbound-link list for `garden-prune`).

Ask for approval. Apply only after the user confirms.

**Exception**: if the user used an explicit trigger phrase ("save this to my vault", "X に Y 足して", "archive X", etc.), treat that as approval — but still show the proposal in the response so they can correct.

### Common: Lint, Commit, Push

Per the vault's Versioning Discipline (declared in `$KG_VAULT/../CLAUDE.md` when present):

1. `pre-commit run --files <every changed file>` — fix any lint or link issues. **Do not bypass with `--no-verify`.**
2. `git add <every changed file>` — stage only the touched files.
3. `git commit -m "<verb>: <subject>"` — one commit per logical operation. The verb (`plant` / `water` / `connect` / `prune`) and subject shape come from the skill's own Commit Subject Examples table.
4. `git push` to the configured remote.

If the vault is not a git repo (`$KG_VAULT/.git` absent), skip the lint/commit/push and warn the user that history is not preserved.

## Skill Routing

```
"capture this" / "save this to my notes" / "vault に書いて" / "メモっといて"
  → garden-plant

"this is a generalizable insight worth keeping" (you detect it; user hasn't asked)
  → garden-plant (propose first, don't write without confirmation)

"what do I have about X?" / "vault に X について書いてる？" / "list <tag> notes" / "先週の daily"
  → garden-survey

(internal — another skill needs to find existing notes before acting)
  → garden-survey

"X に追記" / "<note> に Y を足して" / "tag 足して" / "update <note> with Y"
  → garden-water

(internal — garden-plant found a duplicate and is routing to update instead)
  → garden-water

(internal — garden-survey surfaced a gap like missing tag or broken MOC link)
  → garden-water (propose the patch, ask before applying)

"MOC に X を追加して" / "<MOC> と <child> を link して" / "connect <child> to <MOC>"
  → garden-connect

(internal — garden-survey surfaced an orphan note that should be indexed under a MOC)
  → garden-connect

(internal — garden-plant created a child that belongs under an existing MOC)
  → garden-connect (propose as follow-up to the new note)

"X 消して" / "X を archive して" / "archive these notes" / "X を完全に削除" / "permanently delete X"
  → garden-prune

(internal — garden-survey surfaced empty / stale / orphan notes worth removing)
  → garden-prune (propose per target; require user confirmation; never auto-prune)

"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap

"blog 化して" / "記事化して" / "publish this as a post" / "ブログにして"
  → garden-harvest

(internal — garden-survey surfaced a cluster of permanent notes worth publishing)
  → garden-harvest (propose; gather from the vault, emit into the blog repo, never store a draft)
```

## The Rule

**Invoke knowledge-gardener skills BEFORE writing anything to the vault.** Never write notes by hand from this main skill — always delegate to the operational skill so the format contract is enforced consistently.

## When NOT to Capture

The `garden-plant` skill handles the detailed decision tree, but at the entry layer: do **not** route to capture for ephemeral task state, conversation context, in-progress work, or things already in the vault. The vault is for durable, reusable knowledge — not a transcript.

## Variables

These variables are referenced by all knowledge-gardener skills. Do not redefine in individual skills.

- `KG_VAULT` = value of the `KG_VAULT` environment variable. If unset, skills MUST stop and tell the user: "Set `KG_VAULT` to your vault root (e.g. `export KG_VAULT=~/notes`) and restart the session."
- `KG_BLOG_REPO` = value of the `KG_BLOG_REPO` environment variable — a local path to the blog repo clone, used only by `garden-harvest`. If unset (or the path does not exist), `garden-harvest` MUST stop and tell the user: "Set `KG_BLOG_REPO` to your blog repo root (e.g. `export KG_BLOG_REPO=~/src/blog`) and restart the session." Other skills do not use it.

The vault can be any directory of markdown files with a `README.md` describing its conventions — Obsidian, plain markdown, or anything else.

## Coexistence

- **superpowers** handles software engineering workflows.
- **supernemawashi** handles interpersonal communication and per-person profile data.
- **knowledge-gardener** handles long-term, durable, generalizable knowledge in the user's external vault.
- **auto-memory** (Claude Code built-in) handles per-project short-term memory at `~/.claude/projects/<project>/memory/`.

knowledge-gardener is for knowledge that should outlive a single project or conversation. If the fact is project-scoped and ephemeral, prefer auto-memory.
