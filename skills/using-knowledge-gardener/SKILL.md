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
| `knowledge-gardener:garden-recap` | Wrap up the current Claude Code session by writing what was worked on to today's daily note, so the next session can pick up context |

(One more CRUD skill — `garden-prune` (delete/archive) — is planned and will appear here as it ships.)

## The Format Contract

This plugin is **format-agnostic**. Skills MUST NOT hardcode note structure, filename rules, link syntax, frontmatter fields, folder layout, or any other formatting decision.

Before any write/update operation, the skill MUST:

1. Locate the vault's convention document. Check both:
   - `${KG_VAULT}/README.md` — the vault's own root
   - `${KG_VAULT}/../README.md` — the parent (often the git repo root, when the vault is a subdirectory like `Obsidian/vault/`)

   Both can exist; the vault-root one is more specific and should override the parent on any conflict.
2. Apply the conventions documented there — folder structure, ID/filename rules, link syntax (`[[wikilink]]` vs `[md](path.md)`), frontmatter schema, tag namespace, etc.
3. Also consult any folder-scoped `README.md` inside the directory you're about to write into (e.g. `${KG_VAULT}/<some-folder>/README.md`) for sub-folder-specific conventions.
4. If a critical convention is unclear or absent, stop and ask the user rather than guess. Inventing a new convention silently is a worse failure than asking.

The vault is the source of truth for "how". This plugin is the source of truth for "when".

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

"ここまでまとめて daily に書いて" / "wrap up" / "今日の作業まとめて" / "recap this session"
  → garden-recap
```

## The Rule

**Invoke knowledge-gardener skills BEFORE writing anything to the vault.** Never write notes by hand from this main skill — always delegate to the operational skill so the format contract is enforced consistently.

## When NOT to Capture

The `garden-plant` skill handles the detailed decision tree, but at the entry layer: do **not** route to capture for ephemeral task state, conversation context, in-progress work, or things already in the vault. The vault is for durable, reusable knowledge — not a transcript.

## Variables

These variables are referenced by all knowledge-gardener skills. Do not redefine in individual skills.

- `KG_VAULT` = value of the `OBSIDIAN_VAULT` environment variable. If unset, skills MUST stop and tell the user: "Set `OBSIDIAN_VAULT` to your vault root (e.g. `export OBSIDIAN_VAULT=~/notes`) and restart the session."

The variable name `OBSIDIAN_VAULT` is for ergonomics — many users already have Obsidian. The plugin itself does not require Obsidian; any directory of markdown files with a README describing its conventions works.

## Coexistence

- **superpowers** handles software engineering workflows.
- **supernemawashi** handles interpersonal communication and per-person profile data.
- **knowledge-gardener** handles long-term, durable, generalizable knowledge in the user's external vault.
- **auto-memory** (Claude Code built-in) handles per-project short-term memory at `~/.claude/projects/<project>/memory/`.

knowledge-gardener is for knowledge that should outlive a single project or conversation. If the fact is project-scoped and ephemeral, prefer auto-memory.
