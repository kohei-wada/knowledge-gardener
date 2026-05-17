---
name: garden-survey
description: Use when the user or another skill needs to search, list, or query the vault — by text, tag, frontmatter field, or folder. Returns concise structured results (path, tags, snippet) without modifying anything.
---

# Garden Survey (Read / Search)

Read-only search and listing primitive for the vault. Wraps `grep` / `rg` / a YAML parser in a layer that respects the vault's own conventions (folder roles, archive/template exclusions, frontmatter schema). Used both directly by the user ("what do I have about X?") and internally by other `knowledge-gardener` skills as their lookup primitive.

## When to Use

- User asks "vault に X について書いてる？" / "what do I have about X?" / "list `context/work` notes" / "last week's daily notes"
- Another skill needs to find existing notes before writing (e.g. `garden-plant` duplicate check, `garden-water` target lookup, `garden-promote` candidate discovery)
- Inventory queries: "fleeting notes older than 30 days", "permanent notes tagged `tool/mysql`"

## When NOT to Use

- Need to **write or modify** a note → route to `garden-plant` / `garden-water` / `garden-prune`
- Need **link-graph analysis** (orphan detection, MOC coverage aggregation) — planned for a later release, not this skill
- Need **semantic / embedding-based** search — out of scope; use an external tool

## Process

### Step 1: Resolve Vault Path

1. Read `OBSIDIAN_VAULT` environment variable. If unset: stop and tell the user to set it.
2. Verify the directory exists. If not: stop and report the missing path.

Refer to this path as `$KG_VAULT` for the rest of this skill.

### Step 2: Load Vault Conventions

Read these (stopping when you have enough):

1. `$KG_VAULT/README.md` (vault root, most specific)
2. `$KG_VAULT/../README.md` (parent; many vaults live as a subdirectory of a git repo)
3. `$KG_VAULT/CLAUDE.md` or `$KG_VAULT/../CLAUDE.md` if present (operational instructions)

Extract:

- Which folders hold actual notes vs templates / assets / archives. The latter should be excluded from search by default.
- Tag namespace conventions (whatever schema the README documents; some vaults use namespaced tags like `<namespace>/<value>`, others use flat tags).
- Frontmatter schema (which fields are required, what `tags` looks like).
- Filename conventions for any folder where the user might be searching.

If the vault README documents the layout differently from what you expect, **trust the README**.

### Step 3: Parse the Request

Identify query type(s). A request can combine multiple:

| Query type | Example user phrasing | Internal use |
|------------|----------------------|--------------|
| **text** | "MySQL backup について" / "knowledge-gardener 関連" | `garden-plant` duplicate check by keyword |
| **tag** | "`context/work` のノート" / "`tool/mysql` で `category/backup`" | tag-driven persona context loading |
| **frontmatter** | "先週作った permanent" / "title に MOC を含む" / "tag が空のやつ" | promotion / cleanup candidate discovery |
| **folder + age** | "daily notes 先週分" / "fleeting で 30 日放置" | maintenance / promote pipeline |

If the request is ambiguous (e.g. just a bare keyword), default to **text search** and offer to refine ("tag や日付で絞り込む？").

### Step 4: Execute the Query

Run one or more of the recipes below. Substitute the user's terms. Always exclude folders the README marks as non-content (archives, templates, assets, etc.) unless the request explicitly targets them. The exact folder names vary by vault — read them from the README in Step 2 before running these recipes.

#### 4a. Text Search

Prefer `rg` (ripgrep) when available — much faster on large vaults — and fall back to `grep`:

```bash
# Populate EXCLUDES from the vault README's documented non-content folders.
# Example shape — replace the placeholders with the vault's actual folder names:
EXCLUDES=(-g '!<archive-folder>/**' -g '!<templates-folder>/**' -g '!<assets-folder>/**')
if command -v rg >/dev/null 2>&1; then
  rg --type md -ni "<term>" "$KG_VAULT" "${EXCLUDES[@]}" | head -40
else
  # Substitute --exclude-dir with the vault's actual non-content folder names.
  grep -rni "<term>" "$KG_VAULT" --include='*.md' \
    --exclude-dir=<archive-folder> --exclude-dir=<templates-folder> --exclude-dir=<assets-folder> \
    | head -40
fi
```

Use `-l` instead of `-n` if you only need the file list (faster, less context).

#### 4b. Tag Search

Use Python with PyYAML for robust frontmatter parsing:

```bash
KG_VAULT="$KG_VAULT" TARGET_TAG="<tag>" python3 - <<'PY'
import os, pathlib
try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML not installed: pip install --user pyyaml")
vault = pathlib.Path(os.environ["KG_VAULT"])
target = os.environ["TARGET_TAG"]
# Replace this set with the vault's documented non-content folders (read from the README).
exclude = {"<archive-folder>", "<templates-folder>", "<assets-folder>", ".obsidian"}
hits = []
for f in vault.rglob("*.md"):
    if any(p in exclude for p in f.parts):
        continue
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    if not text.startswith("---"):
        continue
    end = text.find("\n---", 4)
    if end < 0:
        continue
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except Exception:
        continue
    tags = fm.get("tags") or []
    if isinstance(tags, list) and target in tags:
        hits.append((f.relative_to(vault.parent), fm.get("title", ""), tags))
for rel, title, tags in sorted(hits):
    print(f"{rel}\t{title}\t{','.join(map(str, tags))}")
PY
```

Lightweight fallback (less robust — fragile on multi-line YAML and case mismatches):

```bash
# Only finds tags listed as `  - <tag>` lines anywhere in the file head
grep -lE "^  - <tag>$" "$KG_VAULT"/**/*.md 2>/dev/null
```

#### 4c. Frontmatter Query

Same Python recipe shape as Tag Search, swap the predicate:

```python
# Examples (replace inside the loop where you currently check `target in tags`)
# - Created in the last 7 days:
import datetime as dt
cutoff = dt.date.today() - dt.timedelta(days=7)
date_str = fm.get("date") or ""
try:
    note_date = dt.date.fromisoformat(str(date_str).strip('"'))
except ValueError:
    continue
if note_date >= cutoff:
    hits.append(...)

# - Title matches regex:
import re
if re.search(r"MOC$", fm.get("title", "")):
    hits.append(...)

# - Missing required field:
if "tags" not in fm or not fm["tags"]:
    hits.append(...)
```

#### 4d. Folder + Age

`find` is sufficient:

```bash
# Substitute the actual folder names from the vault's README (e.g. the daily-notes folder, the fleeting-notes folder).

# Daily notes from the last 7 days
find "$KG_VAULT/<daily-folder>" -maxdepth 1 -name '*.md' -mtime -7 -printf '%T+ %p\n' \
  | sort

# Fleeting / capture notes older than 30 days (stale candidates for promote/prune)
find "$KG_VAULT/<fleeting-folder>" -maxdepth 1 -name '*.md' -mtime +30 -printf '%T+ %p\n' \
  | sort
```

`-mtime` is filesystem mtime — if the vault is synced via git from another machine, the timestamps may not reflect creation time. In that case, prefer parsing `date:` from frontmatter (4c).

### Step 5: Format Results

Per result, prefer this shape so other skills can consume it consistently:

```
- <path relative to $KG_VAULT/..>
  tags: <comma-separated, or — if none>
  match: <where — title / frontmatter field / line N>
  snippet: <≤ 100 chars, one line>
```

For pure file-list outputs (when only paths matter), one path per line is fine.

### Step 6: Output and Limits

- **Default limit**: top 10 results, sorted by relevance (text-match count) or recency (newest first), depending on query type.
- If more matched, append: `(<N> total — say "show more" or narrow the query)`.
- **No matches**: report "no matches" and suggest a relaxation (e.g. "drop the tag filter? broaden the keyword?").
- **Too many matches** (>100): stop early; ask the user to narrow.

For internal calls from another skill (e.g. `garden-plant` duplicate check), prefer the structured machine-readable output above. The calling skill decides what to render to the user.

## Edge Cases

- **Vault README missing entirely** (neither at `$KG_VAULT/README.md` nor parent): warn the user that exclusion conventions are guessed, but still proceed with sensible defaults.
- **Frontmatter parse failure**: skip the file silently, accumulate a count, and mention `(<N> files had unparseable frontmatter)` at the end so the user can clean them up.
- **Tag specified without namespace** (e.g. `work` instead of `context/work`): try both literal `work` and the namespaced `context/work` if the README documents the namespace. Be explicit about which form matched.
- **Japanese / spaces in filenames**: do not URL-encode anything when displaying paths; quote paths in output so they remain copy-pasteable.
- **Symlinks inside the vault** (e.g. a People dir linking elsewhere): follow them only if the user asks; otherwise list and skip.

## Key Principles

- **Read-only.** Never write, edit, or move files. If the user wants action, route to the appropriate skill.
- **Concise output.** Do not dump file contents into the conversation. One-line snippets, with paths the user can open themselves.
- **Convention-aware.** Respect the vault's documented exclusions and tag namespaces; do not invent search semantics that contradict the README.
- **Stable structured format.** Other skills depend on this; do not silently change the per-result schema.
- **Fail gracefully on missing tooling.** `rg` is preferred but optional; PyYAML is preferred but suggest install if absent. Always have a fallback path.
