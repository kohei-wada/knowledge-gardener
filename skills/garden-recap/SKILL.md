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

### Step 1: Resolve Vault Path

1. Read `OBSIDIAN_VAULT`. Stop and ask if unset.
2. Verify directory exists.

Refer to it as `$KG_VAULT`.

### Step 2: Load Vault Conventions

Read in order:

1. `$KG_VAULT/README.md` and `$KG_VAULT/../README.md` — folder layout, link syntax, frontmatter schema
2. `$KG_VAULT/CLAUDE.md` or `$KG_VAULT/../CLAUDE.md` — operational rules (including Versioning Discipline)
3. The daily-note template — wherever the README points to it

Extract:

- **Daily-note folder** — whatever the README names it.
- **Daily-note filename convention** — whatever the README specifies (e.g. an ISO date, a Luhmann ID, etc.).
- **Daily-note template** (sections, frontmatter, default tag list).
- **Vault language** for note bodies — whatever the existing notes use. The README may be in a different language; follow the notes, not the README.

### Step 3: Inventory the Session

Gather concrete facts to fill the recap. **Don't make things up — only record what you can support with evidence from the conversation, file state, or `git log`.**

- **Time range**: when did the session effectively start? Use the conversation start (or the user's first substantive message) and `date` for "now".
- **Outcomes**: what was decided / built / fixed / shipped this session? One sentence each.
- **Files touched** — concrete inventory:
  - For each repo touched in this session (identify from the conversation), run `git log --since='<session-start>' --oneline --author='<git user>'` or `git log --since=<today-00:00> --oneline`.
  - Or `git diff --stat` if commits not yet made.
  - Aggregate as a short list with one-line descriptions.
- **New notes planted today**: query the vault for `date: <today>` frontmatter or `git -C "$KG_VAULT/.." log --since=<today-00:00> --name-only` to find newly-added notes. List them.
- **Decisions / principles surfaced**: distill the conversation. Any new rules, gotchas, or trade-offs that should outlive the session.
- **Open follow-ups**: TODOs or deferrals the user mentioned but didn't act on. State them so future-you doesn't lose the thread.

Cap each list to roughly the most-significant ~5 items. A recap is a summary, not a transcript.

### Step 4: Locate Today's Daily Note

- Compute today's date in the vault's filename convention (typically `YYYY-MM-DD`).
- Build the full path: `$KG_VAULT/<daily-folder>/<date>.<ext>` per the conventions discovered in Step 2.
- Check existence:
  - **Exists** → this will be an **append** operation. Read the file in full (use the Read tool, not `Bash head/cat`, so the Edit tool will accept your changes later).
  - **Missing** → this will be a **new file**. Load the daily-note template content to use as scaffold.

### Step 5: Draft the Recap

Match the vault's daily-note template structure. Typical sections (adapt to whatever the actual template says):

- **今日の気づき・学び** / "Learnings": bullet the technical learnings + process improvements from Step 3.
- **KPT (Keep / Problem / Try)**: what worked, what didn't, what to try next session.
- **メモ** / "Notes": short factual remarks that don't fit elsewhere.
- **関連リンク** / "Related Links":
  - 前日の振り返り (link to yesterday's daily if it exists)
  - 今日作成したノート (links to notes planted today — relative paths per vault link convention)
  - Any cross-repo work mentioned (commits in `ore` / `knowledge-gardener` etc.)

**Crucial**:

- Use the **vault's** link syntax (per its README — usually standard markdown, no URL encoding even for spaces in filenames).
- Use the **vault's** content language (most likely Japanese; the daily template you just read should make this obvious).
- For an **append** to an existing daily note: do NOT overwrite earlier content. Either integrate new bullets into the existing template sections, or add a new sub-section like `### Session <HH:MM>` under an existing heading. The user's prior session in this same day stays.

### Step 6: Propose, Don't Commit

Show the user:

1. The target path (`$KG_VAULT/04_DailyNotes/YYYY-MM-DD.md` or equivalent).
2. The **diff** (for append) or **full draft** (for new file).
3. The change is large enough — feel free to break into "outcomes / files / learnings / follow-ups" subsections in your proposal output so the user can red-line specific parts.
4. One-line rationale: "Capturing today's session so the next one can pick up context."

Ask for approval. Apply only after confirmation, unless the user explicitly said "wrap up and write it" / "ここまでまとめて書いて".

### Step 7: Apply the Change

- **New daily note**: use the **Write tool** to create the file with the full content.
- **Append to existing**: use the **Edit tool** with appropriate anchors. Per garden-water Step 5, you must have called the Read tool on the file first; `Bash head/cat` doesn't count.

For appending, prefer anchoring on a stable section header (e.g. `## 関連リンク` or whichever exists) and inserting before or after it, rather than trying to match a long block that might have been autofixed by markdownlint.

### Step 8: Lint, Commit, Push

Per the vault's Versioning Discipline (declared in `$KG_VAULT/../CLAUDE.md` when present):

1. `pre-commit run --files <changed daily note>` — fix any lint or link issues. Do not bypass with `--no-verify`.
2. `git add <changed daily note>` — only this file.
3. Commit subject:
   - New daily note: `plant: <YYYY-MM-DD> daily (session recap)`
   - Append to existing: `water: <YYYY-MM-DD> daily session recap`
4. `git push`.

Body of the commit message: optional one-paragraph summary of what was recapped. Keep terse.

## Edge Cases

- **No daily-note convention documented**: the vault README doesn't tell you where daily notes go or how they're named → stop and ask the user; do not invent a location.
- **Daily folder doesn't exist** (e.g. vault layout differs from expectation): stop and surface the gap. Suggest the user pick the correct folder or update the README.
- **Today's daily note already has a recap from earlier in the day**: append a new sub-section (e.g. `### Session <HH:MM> 〜`), do not overwrite the previous recap.
- **Session inventory turns up nothing meaningful**: tell the user "nothing significant to recap" rather than padding the daily note with filler. Better to skip than to write noise.
- **`git log --since` returns nothing** because all commits are in the future (clock skew, or the inventory window is wrong): widen the window or fall back to `git status` for uncommitted changes.
- **Pre-commit fails on the new daily note** (e.g. broken link to a planted note): fix the link or the note, then retry. Don't `--no-verify`.

## Key Principles

- **Evidence over recollection.** When listing files touched or notes planted, support each item with `git log` / file existence / actual conversation message. Don't paraphrase your own memory of what "probably" happened.
- **One commit per session recap.** The daily note may collect multiple sessions in one day, but each recap is its own commit so history stays readable.
- **Mirror the daily template's structure.** Don't impose a recap format that contradicts what the template already provides. Follow the vault.
- **Future-you reads this.** Write so that next session opens the daily note and immediately knows what shape today was in — outcomes first, files next, learnings + follow-ups last.
- **Preserve prior content on append.** Earlier sessions' content in today's daily note is sacred. Add, don't replace.
- **Atomic, like the rest of the gardener.** Don't bundle "today's recap + tag fix + new permanent note" into one commit. Recap is one operation.
