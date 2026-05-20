---
name: garden-recap
description: Use when the user wants to wrap up the current Claude Code session by writing what was worked on to today's daily note in the vault, so the next session can pick up context. Pairs garden-plant (new daily note) or garden-water (append to existing) under the hood.
---

# Garden Recap (Session Wrap-up)

Capture the current session's work — outcomes, files touched, decisions, follow-ups — to today's daily note. Designed to be invoked **before** the user ends a session so future sessions (today or later) can recover context without re-reading the entire transcript.

## When to Use

- User says: "ここまで daily にまとめて" / "wrap up" / "今日の作業まとめて" / "recap this session" / "session を切る前に記録"
- About to switch tasks and want a clean handoff point
- End of a productive working block where context is worth preserving

## When NOT to Use

- A single durable insight needs capturing → `garden-plant` (atomic note, not daily journal entry)
- Updating a specific existing note → `garden-water`
- Just searching → `garden-survey`
- The session was trivial (read-only exploration, no outcomes): skip — don't pollute the daily note with empty recaps

## Process

### Step 1: Pre-flight Setup

Follow [Pre-flight Setup](../using-knowledge-gardener/SKILL.md#pre-flight-setup-shared-by-all-operational-skills) in `using-knowledge-gardener` to resolve `$KG_VAULT` and load vault conventions. Additionally read the **daily-note template** wherever the README points to it.

From the conventions + template, extract for this skill (at minimum):

- Where daily notes live (folder).
- How daily notes are named (filename convention).
- What the daily-note template looks like — sections, frontmatter, default tags.
- What language note bodies are written in.
- How multiple sessions in the same day are handled (sub-heading convention, if any).
- The vault's link syntax.

If any of these are not discoverable from the README or templates, stop and ask the user. Do not invent defaults.

### Step 2: Inventory the Session

Gather concrete facts to fill the recap. **Don't make things up — only record what you can support with evidence from the conversation, file state, the session log, or `git log`.**

#### 3a. Read the session log (Phase 1 + 2)

Since `v0.8.0`, a `PostToolUse` hook captures one log line per material tool call to `$XDG_STATE_HOME/knowledge-gardener/sessions/<YYYY-MM-DD>-<sid8>.log`. `v0.9.0` adds an aggregator script that turns those raw lines into a recap-ready summary.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/garden-recap/recap_aggregate.py"
```

By default it picks the most-recently-modified session log for today (≈ the active session). Useful flags:

- `--all` — include every session for today (when the user did multiple Claude sessions).
- `--sid <sid8>` — pick a specific session.
- `--date YYYY-MM-DD` — aggregate a different day.

The output is plain text in this shape (per session):

```
## Session <HH:MM> - <HH:MM> (sid8: <sid8>)
Duration: <N>m, <N> captured tool calls.

### Files touched
- <path> (<n> edits)

### Bash highlights
- <command>

### Other tool activity
- Agent: <n> dispatch(es) — <subagent_types>
- WebFetch/WebSearch: <n>
- MCP: <server>(<n>), <server>(<n>)
- Errors: <n>
```

If the output contains at least one session block with a non-zero entry count, **treat it as the evidence inventory** for Outcomes / Files / Tool activity. Cross-check with `git log --since=<today-00:00>` for vault changes when summarizing what was committed.

If the output is `0 session(s) found` or contains only zero-entry sessions, the hook wasn't capturing (older plugin install, or session predates `v0.8.0`). **Fall back to recollection-based inventory** as documented in 3b.

#### 3b. Recollection fallback (no log available)

- **Time range**: when did the session effectively start? Use the conversation start (or the user's first substantive message) and `date` for "now".
- **Outcomes**: what was decided / built / fixed / shipped this session? One sentence each.
- **Files touched** — concrete inventory:
  - For each repo touched in this session (identify from the conversation), run `git log --since='<session-start>' --oneline --author='<git user>'` or `git log --since=<today-00:00> --oneline`.
  - Or `git diff --stat` if commits not yet made.
  - Aggregate as a short list with one-line descriptions.
- **New notes planted today**: query the vault for `date: <today>` frontmatter or `git -C "$KG_VAULT/.." log --since=<today-00:00> --name-only` to find newly-added notes. List them.

#### 3c. Always from conversation (both paths)

The log records actions, not reasoning. These items always come from conversation context regardless of whether 3a or 3b ran:

- **Decisions / principles surfaced**: any new rules, gotchas, or trade-offs that should outlive the session.
- **Open follow-ups**: TODOs or deferrals the user mentioned but didn't act on.

Cap each list to roughly the most-significant ~5 items. A recap is a summary, not a transcript.

### Step 3: Locate Today's Daily Note

- Format today's date per the vault's filename convention discovered in Step 1.
- Build the full path under the daily-note folder discovered in Step 1.
- Check existence:
  - **Exists** → this will be an **append** operation. Read the file in full with the Read tool (not `Bash head/cat`, which doesn't count toward the Edit tool's per-file read tracking).
  - **Missing** → this will be a **new file**. Load the daily-note template content to use as scaffold.

### Step 4: Draft the Recap

The daily-note template (loaded in Step 1) is the structure. Fill each section the template defines with content from your Step 2 inventory. Do not invent sections the template does not define; do not impose section names from elsewhere.

- Write in the language declared by the README (or the language the existing notes use, if the README is silent).
- Use the link syntax declared by the README. Do not normalise links to a different syntax.
- For an **append** to an existing daily note: do NOT overwrite earlier content. Apply the README's multi-session convention if one is documented; if none is documented, integrate new bullets into existing template sections without restructuring them.

### Step 5: Propose, Don't Commit

Follow [Common: Propose, Don't Commit](../using-knowledge-gardener/SKILL.md#common-propose-dont-commit). For this skill, show:

1. The target path (the absolute path resolved in Step 3).
2. The **diff** (for append) or **full draft** (for new file).
3. Feel free to break the draft into "outcomes / files / learnings / follow-ups" subsections so the user can red-line specific parts.
4. One-line rationale: "Capturing today's session so the next one can pick up context."

Trigger phrases that count as implicit approval: "wrap up and write it" / "ここまでまとめて書いて".

### Step 6: Apply the Change

- **New daily note**: use the **Write tool** to create the file with the full content.
- **Append to existing**: use the **Edit tool** with appropriate anchors. Per garden-water Step 4, you must have called the Read tool on the file first; `Bash head/cat` doesn't count.

For appending, prefer anchoring on a stable section header from the template (whichever exists in the file) and inserting before or after it, rather than trying to match a long block that might have been autofixed by markdownlint.

### Step 7: Lint, Commit, Push

Follow [Common: Lint, Commit, Push](../using-knowledge-gardener/SKILL.md#common-lint-commit-push). Commit subject for this skill depends on whether the daily note is new or appended:

- New daily note: `plant: <date> daily (session recap)`
- Append to existing: `water: <date> daily session recap`
- `<date>` follows whatever format the daily-note filename uses (per the README).

Body of the commit message: optional one-paragraph summary of what was recapped. Keep terse.

## Edge Cases

- **No daily-note convention documented**: the vault README doesn't tell you where daily notes go or how they're named → stop and ask the user; do not invent a location.
- **Daily folder doesn't exist** (e.g. vault layout differs from expectation): stop and surface the gap. Suggest the user pick the correct folder or update the README.
- **Today's daily note already has a recap from earlier in the day**: append per the README's multi-session convention. Do not overwrite the previous recap. If the README has no multi-session rule, integrate new bullets into the existing template sections rather than restructuring the file.
- **Session inventory turns up nothing meaningful**: tell the user "nothing significant to recap" rather than padding the daily note with filler. Better to skip than to write noise.
- **`git log --since` returns nothing** because all commits are in the future (clock skew, or the inventory window is wrong): widen the window or fall back to `git status` for uncommitted changes.
- **Pre-commit fails on the new daily note** (e.g. broken link to a planted note): fix the link or the note, then retry. Don't `--no-verify`.

## Key Principles

- **Evidence over recollection.** When listing files touched or notes planted, support each item with the session log / `git log` / file existence / actual conversation message. Don't paraphrase your own memory of what "probably" happened.
- **One commit per session recap.** The daily note may collect multiple sessions in one day, but each recap is its own commit so history stays readable.
- **Mirror the daily template's structure.** Don't impose a recap format that contradicts what the template already provides. Follow the vault.
- **Future-you reads this.** Write so that next session opens the daily note and immediately knows what shape today was in — outcomes first, files next, learnings + follow-ups last.
- **Preserve prior content on append.** Earlier sessions' content in today's daily note is sacred. Add, don't replace.
- **Atomic, like the rest of the gardener.** Don't bundle "today's recap + tag fix + new permanent note" into one commit. Recap is one operation.
