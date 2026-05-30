# garden-harvest — Design

- **Date**: 2026-05-30
- **Status**: Approved (pending spec review)
- **Tracking issue**: [knowledge-gardener#29](https://github.com/Kohei-Wada/knowledge-gardener/issues/29)
- **Sibling skills**: [garden-plant](../../skills/garden-plant/SKILL.md) (capture), [garden-survey](../../skills/garden-survey/SKILL.md) (read), [garden-recap](../../skills/garden-recap/SKILL.md) (session wrap-up)

## Goal

Ship a **stateless pipe** that turns vault knowledge into a published blog post:

```
vault (knowledge, source of truth)
  ──[gather: declared by the VAULT README]──▶ dialogue (shape the post with the user)
  ──[emit + mask: declared by the BLOG repo README]──▶ blog repo (the published artifact)
```

`garden-harvest` is the "take mature knowledge out into the world" verb — the
counterpart to `garden-plant` (capture). It owns **WHEN / orchestration only**;
it owns no format.

## Why this exists

A blog draft is *production* state (done/undone), not knowledge (true/false).
Persisting a draft inside the knowledge vault contradicts "the vault is pure
knowledge", and the published body already lives in the blog repo — so a
vault-side draft is double-management. This skill removes the draft-as-stored-state
problem: the in-progress draft is the **conversation**, never a file.

## The three contracts (all resolved from a README entry point)

The skill hardcodes none of the conventions below. It resolves each by reading a
README and following the pointers that README declares — exactly the
format-agnostic pre-flight pattern the rest of the family uses.

| Convention | Entry point | How the skill resolves it |
|---|---|---|
| **Gather** — what source material to assemble | **vault README** (`KG_VAULT`) | Read the README; follow its "Blog" section, which declares the gather convention (for this Zettelkasten vault: *bundle the relevant `03_PermanentNotes/` notes and the notes they link to*). |
| **Emit / mask / format / parity** — how to write, mask, and ship a post | **blog repo README** (`KG_BLOG_REPO`) | Read the blog repo README; follow the pointer it declares to the conventions doc. The skill never hardcodes the doc path (e.g. `docs/content-creation.md`). Bilingual parity, frontmatter, the worth-publishing test, and PII-masking all live behind that pointer — the skill does not know them a priori. |
| **Blog repo location** — where the artifact is written | **env `KG_BLOG_REPO`** | A local path to the blog repo clone, resolved the same way `KG_VAULT` is. If unset, stop and tell the user to set it (do not guess a path). |

**Stop-and-ask, never invent.** If either README does not declare the conventions
the skill needs (gather on the vault side; write/mask on the blog side), the skill
stops and asks the user rather than inventing a default. This mirrors the
existing pre-flight contract.

## Process

Propose-then-confirm throughout, matching the other write skills.

1. **Pre-flight.**
   - Resolve `KG_VAULT` (per the shared [Pre-flight Setup](../../skills/using-knowledge-gardener/SKILL.md#pre-flight-setup-shared-by-all-operational-skills)) and load vault conventions; extract the **gather** convention from the vault README's blog section.
   - Resolve `KG_BLOG_REPO`. If unset or the path does not exist, stop and report (same failure mode as a missing `KG_VAULT`).
   - Read the **blog repo README** and follow its declared pointer to the write/mask conventions doc. If the README declares no such pointer, stop and ask.
2. **Gather.** Following the vault README's gather convention, assemble the relevant permanent notes (and the notes they link to) for the topic as raw material. Read real-valued notes directly — they are visible to the user during the dialogue. Nothing is written to or stored under the vault.
3. **Dialogue.** Shape the post with the user. The draft *is* this conversation — no persistent draft file is created anywhere.
4. **Emit + mask.** Produce the post per the blog repo's resolved conventions, including whatever those conventions require (e.g. bilingual parity) and applying the PII-masking rules they declare. Apply the **worth-publishing test** the conventions define; if the candidate fails it, stop without publishing (there is no "rejected" artifact to file — the decision is simply not to emit).
5. **Commit.** Write the post file(s) into the blog repo and **commit** there. Stop at commit — **do not push** (push triggers deploy; that stays a manual user action). Follow the blog repo's documented verify/lint steps before committing, and the family's propose-then-confirm + commit discipline.

## State policy

- **No persistent draft** — not in the vault, not in the blog repo, not in a state dir. The conversation is the draft.
- **No disposable cache in v1.** The `#29` design permits a deletable, rebuildable cache under gardener's state dir, but it is explicitly out of scope for the first version (YAGNI). Revisit only if multi-session drafting proves necessary.

## Family integration

- Add a verb-first entry routed from `using-knowledge-gardener` (Skill Routing + the skill table), consistent with the existing family.
- Reference the canonical **Pre-flight Setup** and **Common Workflow Steps** sections in `using-knowledge-gardener` rather than duplicating them.
- Reuse the propose / lint / commit discipline already shared by the write skills. The one twist: the lint/commit target is the **blog repo**, not the vault, and the sequence stops before push.
- Declare `KG_BLOG_REPO` alongside `KG_VAULT` in the **Variables** section of `using-knowledge-gardener` (with the same "unset → stop and tell the user" contract), so the new config surface is documented in one canonical place.

## Acceptance (from #29)

- A new verb-first skill routed from `using-knowledge-gardener`, consistent with the family.
- The skill reads gather conventions from the vault README and emit/mask conventions from behind the blog repo README's pointer — nothing about bundling, post format, masking, or parity is hardcoded in the skill.
- No durable draft artifact is created in the vault (and, in v1, no cache either).
- If either README does not declare the conventions it needs, the skill stops and asks rather than inventing them.
- Propose-then-confirm and lint/commit discipline match the other write skills; the operation targets the blog repo and stops at commit.

## Out of scope

- Owning blog content or its lifecycle storage — the blog repo owns the artifacts and their format.
- Running the static-site build/deploy — the skill stops at commit; `push` (→ Netlify deploy) is a manual user action.
- The vault-side cleanup of the old `05_Blog/` area and lifecycle markers — already done separately (vault README is now gather-only; `05_Blog/` removed).
- A disposable working-state cache (deferred from v1).

## Open decisions resolved during brainstorming

- **Name**: `garden-harvest` (verb-first, gardening metaphor: plant → grow → harvest).
- **Emit boundary**: commit in the blog repo, no push.
- **Language/parity**: not the skill's concern — it obeys whatever the blog repo conventions declare.
- **Conventions discovery**: always from a README entry point, following declared pointers; never a hardcoded doc path.
- **Cache**: none in v1.
