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

### Step 3: Establish the topic

Before gathering anything, make sure there is a concrete topic. If the user named one, use it. If the skill was invoked cold with no topic, **ask what to publish** — or offer `garden-survey` to surface publish-worthy clusters of permanent notes and pick from those. Do not guess a topic and start gathering.

### Step 4: Gather

Following the vault's gather convention, assemble the relevant permanent notes (and the notes they link to) for the topic as raw material. Read the **real-valued** notes directly — they are visible to you during the dialogue. Write nothing to the vault.

### Step 5: Dialogue

Shape the post with the user — angle, structure, what first-hand experience it carries. The draft *is* this conversation; create no draft file anywhere.

Apply the blog's **worth-publishing test** as a gate: if the candidate carries no experiment / failure / judgment / first-hand layer, say so and stop without publishing. There is no "rejected" artifact to file — the outcome is simply not to emit.

Treat the vault notes as **raw material, not verified truth** — a claim being written down does not make it correct or settled. During the dialogue, surface claims the user should vet, and cut anything the user is not confident is correct or does not want to assert publicly. The post states only what the author stands behind. (This is distinct from the worth-publishing test: that asks "is it first-hand?", this asks "is it true / does the author endorse it?")

### Step 6: Emit + mask

Produce the post per the blog repo's resolved conventions, satisfying every structural requirement they declare (e.g. locale parity) and applying their **PII-masking rules** to the emitted copy — the source notes keep the real values; only the public copy is masked.

**When the conventions require multiple locales (parity), draft and iterate in ONE primary locale first**, then translate to the others once the content is signed off. Pick the primary locale to fit the user — infer it from the conversation or ask; **do not force a fixed language**. Getting content approval in one locale before translating avoids re-translating after every revision.

Follow [Common: Propose, Don't Commit](../using-knowledge-gardener/SKILL.md#common-propose-dont-commit): show the target path(s) under `$KG_BLOG_REPO`, the full draft of each file, a one-line rationale, and an explicit **masking confirmation** (what real values were redacted to what). Apply only after the user confirms.

### Step 7: Commit (not push)

In the blog repo, run the repo's documented verify/lint steps, then **commit** the post file(s) (all locales). **Stop at commit — do not push.** Push triggers deployment and stays a manual user action; say so.

This mirrors [Common: Lint, Commit, Push](../using-knowledge-gardener/SKILL.md#common-lint-commit-push) except the target is the **blog repo** (not the vault) and the sequence ends before push. Use a commit subject in the blog repo's own convention (the conventions doc declares it).

## State

- **No persistent draft** — not in the vault, the blog repo, or a state dir.
- **No cache.** Each invocation re-gathers from the vault.
