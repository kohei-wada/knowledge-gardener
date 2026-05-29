# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

knowledge-gardener is a Claude Code skill library (plugin) that decides **when** to capture, update, link, or prune long-term knowledge in the user's external vault. It is intentionally **format-agnostic**: the vault's own README owns the "how" (note structure, filenames, link syntax, tags, folder layout); this plugin owns only the "when".

## Architecture

- **Plugin type**: Claude Code skill library (same pattern as [supernemawashi](https://github.com/Kohei-Wada/supernemawashi) and [superpowers](https://github.com/obra/superpowers))
- **Skills**: Markdown files in `skills/<skill-name>/SKILL.md` with YAML frontmatter
- **Hooks**:
  - `SessionStart` injects `using-knowledge-gardener` into every session
  - `PostToolUse` (Phase 1 of issue #1) runs `recap/capture.py` to append a one-line evidence entry per material tool call to `$XDG_STATE_HOME/knowledge-gardener/sessions/<date>-<sid8>.log` — best-effort, never blocks Claude
  - `Stop` (Phase 3 of issue #1, **opt-in via `KG_AUTO_RECAP=1`**, registered with `async: true`) runs `recap/auto_recap.py` to silently spawn headless Claude, generate today's session block, and `git commit && git push` to the vault. Fire-and-forget — Claude returns control to the user immediately while the recap composes in the background. Default-off so OSS installs don't surprise users with auto-commits.
- **Vault location**: Resolved from `KG_VAULT` env var at runtime; not stored in this repo
- **Session log location**: `$XDG_STATE_HOME/knowledge-gardener/sessions/` (fallback `~/.local/state/`). Machine-local derived state, not vault content. `garden-recap` consumes these logs via `recap/recap_aggregate.py` since `v0.9.0` (Phase 2); falls back to recollection when no logs exist. Since `v0.10.0` (Phase 3) the `Stop` hook can silently auto-write the same recap when `KG_AUTO_RECAP=1` (orchestrator at `recap/auto_recap.py`).

## Skills

The user-facing skill list (purposes, status) lives in [README.md](README.md#skills) — see it there to avoid drift. Maintainer-relevant detail:

- Entry point: `using-knowledge-gardener` (declares variables, the format contract, common workflow steps).
- Operational skills: `garden-plant` (C), `garden-survey` (R), `garden-water` (U), `garden-prune` (D), plus `garden-connect` (link edges) and `garden-recap` (session wrap-up).
- Each operational SKILL.md references the canonical "Pre-flight Setup" and "Common Workflow Steps" sections inside `using-knowledge-gardener` rather than duplicating them.

## Key Conventions

- **Format-agnostic**: skills MUST read the vault's README for conventions before writing. Never hardcode filename rules, frontmatter schemas, link syntax, or folder layout in a skill.
- **Propose, don't commit by default**: writes are proposed and confirmed unless the user explicitly asked to save.
- **Vault path comes from env**: `KG_VAULT`. Skills must fail loudly if unset, not invent a default.
- **No vault data in this repo**: the user's knowledge stays on their machine. This repo ships only program (skills + hooks).
- All documentation and skill files are written in English.
