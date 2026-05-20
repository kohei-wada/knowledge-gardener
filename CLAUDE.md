# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

knowledge-gardener is a Claude Code skill library (plugin) that decides **when** to capture, update, link, or prune long-term knowledge in the user's external vault. It is intentionally **format-agnostic**: the vault's own README owns the "how" (note structure, filenames, link syntax, tags, folder layout); this plugin owns only the "when".

## Architecture

- **Plugin type**: Claude Code skill library (same pattern as [supernemawashi](https://github.com/Kohei-Wada/supernemawashi) and [superpowers](https://github.com/obra/superpowers))
- **Skills**: Markdown files in `skills/<skill-name>/SKILL.md` with YAML frontmatter
- **Hooks**: Session-start hook injects `using-knowledge-gardener` skill into every session
- **Vault location**: Resolved from `KG_VAULT` env var at runtime; not stored in this repo

## Skills

| Skill | Purpose |
|-------|---------|
| using-knowledge-gardener | Entry point — routes requests to operational skills, declares variables and the format contract |
| garden-plant | Captures a new durable insight as a vault note, using conventions read from the vault's README |
| garden-survey | Read-only search/listing primitive (text, tag, frontmatter, folder). Used directly and by other skills |
| garden-water | Updates an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits |
| garden-connect | Links an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
| garden-prune | Removes a named note — archive by default (git mv into the vault's documented archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; link cleanup is garden-water's job |
| garden-recap | Wraps up a session by writing what was worked on to today's daily note, so the next session can pick up context |

## Key Conventions

- **Format-agnostic**: skills MUST read the vault's README for conventions before writing. Never hardcode filename rules, frontmatter schemas, link syntax, or folder layout in a skill.
- **Propose, don't commit by default**: writes are proposed and confirmed unless the user explicitly asked to save.
- **Vault path comes from env**: `KG_VAULT`. Skills must fail loudly if unset, not invent a default.
- **No vault data in this repo**: the user's knowledge stays on their machine. This repo ships only program (skills + hooks).
- All documentation and skill files are written in English.
