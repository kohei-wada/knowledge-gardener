# knowledge-gardener

A Claude Code plugin for **tending a long-term knowledge base** from inside your coding sessions.

## What It Does

Decides **when** to capture, update, link, or prune durable knowledge in your external vault (Obsidian, a plain markdown folder, anything with a README). Defers **how** — note format, filename rules, link syntax, frontmatter, folder layout — to the vault's own README. This separation is the whole point.

> The vault is the source of truth for **how**.
> This plugin is the source of truth for **when**.

## Why This Exists

Most "Obsidian-for-Claude" plugins hardcode a note format (PARA, Zettelkasten with Luhmann IDs, daily-note schemas, etc.). That makes them useful only if your vault matches the plugin's assumptions. The moment your vault has its own README spelling out conventions, those plugins fight you.

`knowledge-gardener` flips it: the **plugin reads your vault's README** before each operation and applies whatever conventions are documented there. Bring your own format.

## Installation

Inside Claude Code:

```
/plugin marketplace add Kohei-Wada/knowledge-gardener
/plugin install knowledge-gardener@knowledge-gardener
```

Set the vault path in your shell:

```bash
export OBSIDIAN_VAULT=~/path/to/your/vault
```

Restart your Claude Code session.

### Vault Prerequisites

Your vault MUST have a `README.md` that documents at least:

- **Folder layout** — where do different kinds of notes go?
- **Filename rules** — kebab-case? Luhmann ID? date prefix?
- **Link syntax** — `[[wikilink]]`, `[md](rel-path.md)`, or both?
- **Frontmatter schema** — required fields, if any
- **Tag namespace** — any constraints

The README can live at either:

- `$OBSIDIAN_VAULT/README.md` — vault root (most specific, wins on conflict), or
- `$OBSIDIAN_VAULT/../README.md` — parent directory (common when the vault is a subdirectory of a git repo, e.g. `Obsidian/vault/`)

`garden-plant` reads both and merges; folder-scoped READMEs (e.g. `$OBSIDIAN_VAULT/06_People/README.md`) are also consulted when relevant.

If no README is found in either location, `garden-plant` will refuse to write and tell you what's missing. That's intentional: silent defaults are how vaults end up inconsistent.

## How It Works

1. **You converse with Claude as normal.**
2. **A durable insight surfaces** — a decision, a lesson, a workflow, a reference worth remembering.
3. **Claude proposes a note** — path, content, and rationale — formatted per your vault's README.
4. **You approve.** Claude writes the file. (Or skip the approval step by saying "save this to my vault".)
5. **You commit on your own cadence.** The plugin never auto-commits or pushes.

## What's Inside

### Skills

| Skill | What it does |
|-------|-------------|
| `using-knowledge-gardener` | Entry point — routes requests, declares the format contract |
| `garden-plant` | **(implemented)** Capture a new durable insight as a vault note |
| `garden-survey` | **(implemented)** Read-only search/listing primitive (text, tag, frontmatter, folder). Used directly and by other skills |
| `garden-water` | **(implemented)** Update an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits |
| `garden-recap` | **(implemented)** Wrap up a session by writing what was worked on to today's daily note, so the next session can pick up context |
| `garden-connect` | **(implemented)** Link an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
| `garden-prune` | **(implemented)** Remove a named note — archive by default (git mv into the vault's archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; cleanup goes through garden-water |

### What Counts as "Durable"

`garden-plant` captures things like:

- Decisions and principles ("from now on we...", "the rule is...")
- Non-obvious conclusions reached after deliberation
- Reusable workflows, recipes, and configs
- Lessons learned from incidents or surprises
- Architectural choices with reasoning
- Pointers to external resources (dashboards, ticket systems)

It explicitly does **not** capture:

- Per-project task state (use Claude Code's built-in auto-memory)
- Per-person behavioral notes (use [supernemawashi](https://github.com/Kohei-Wada/supernemawashi))
- Conversation context or in-progress reasoning
- Anything already in the vault

## Philosophy

- **Format is data, not code.** Conventions live in the vault, not in the plugin. Change conventions → no plugin change needed.
- **Propose, don't commit.** The vault is your brain. Writes need consent.
- **Fail loudly on missing convention.** Better to stop and ask than to invent a default that drifts from the rest of the vault.
- **Never bypass vault lints.** If your vault has pre-commit checks, they win.
- **Atomic where the vault is atomic.** Mirror the vault's granularity instead of imposing one.

## Coexistence with Other Skill Libraries

| Library | Domain |
|---------|--------|
| [superpowers](https://github.com/obra/superpowers) | Software engineering workflows |
| [supernemawashi](https://github.com/Kohei-Wada/supernemawashi) | Interpersonal communication & per-person profiles |
| **knowledge-gardener** | Long-term, format-agnostic vault curation |
| Claude Code auto-memory | Per-project short-term memory |

They do not overlap. `knowledge-gardener` is specifically for knowledge that should outlive a single project or conversation.

## Requirements

- [Claude Code](https://claude.ai/code)
- A markdown vault (folder of `.md` files) with a `README.md` that documents its own conventions
- `OBSIDIAN_VAULT` env var set to the vault root

## Contributing

Issues and PRs welcome at [github.com/Kohei-Wada/knowledge-gardener](https://github.com/Kohei-Wada/knowledge-gardener).

## License

MIT
