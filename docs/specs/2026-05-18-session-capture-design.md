# Session Capture (Phase 1) — Design

- **Date**: 2026-05-18
- **Status**: Approved (pending spec review)
- **Target release**: knowledge-gardener v0.7.0
- **Source RFP**: [GitHub issue #1](https://github.com/Kohei-Wada/knowledge-gardener/issues/1)
- **Phase**: 1 of 3 (capture only; garden-recap consumer is Phase 2)

## Goal

Ship the **capture half** of issue #1: a `PostToolUse` hook that appends a one-line evidence entry per material tool call to `~/.local/share/knowledge-gardener/sessions/<date>-<sid>.log`. `garden-recap` itself does **not** change in this phase — it continues to recall from Claude's context. The log file is consumed in Phase 2 (v0.8.0).

## Why split

Capture is testable independently: install the plugin, run normal Claude sessions, inspect `~/.local/share/knowledge-gardener/sessions/`. No skill behavior changes, so there is zero risk of regressing existing recap UX. The runtime data from Phase 1 also informs Phase 2's filter calibration and `garden-recap` parsing format choices.

## Scope (v0.7.0)

### In scope

- `hooks/hooks.json` registers a `PostToolUse` hook with matcher `*` and a 5-second timeout.
- `scripts/capture.py` reads the hook payload from stdin, decides whether the tool call is "material", composes a one-line entry, and appends it to a per-day per-session log file.
- Log directory: `~/.local/share/knowledge-gardener/sessions/`. Matches the supernemawashi convention (`~/.local/share/supernemawashi/profiles/`).
- Log filename: `<YYYY-MM-DD>-<sid8>.log` where `<sid8>` is the first 8 chars of the session UUID (collision-resistant enough for a per-day basis; the full UUID is overkill for human readability and the session metadata stays accessible via the file's mtime).
- Log entry shape (plain text, one event per line):
  - `HH:MM tool=<Tool> target=<one-line> [status=ok|err]`
- Filter (denylist; everything not denied is captured):
  - **Always skipped**: `Read`, `TodoWrite`, `TaskCreate`, `TaskUpdate`, `TaskGet`, `TaskList`, `TaskOutput`, `TaskStop`, `Skill`, `AskUserQuestion`, `ToolSearch`, `ScheduleWakeup`, `ShareOnboardingGuide`.
  - **`Bash` only**: skip when the command's first token matches the trivial-command denylist: `ls`, `pwd`, `cat`, `head`, `tail`, `find`, `echo`, `which`, `type`, `grep`, `rg`, `wc`, `sort`, `uniq`, `date`, `printf`, `true`, `false`.
- Privacy strip at the hook boundary, before write:
  - Strip any text matching `<private>...</private>` (greedy, multi-line).
  - Strip any token-like string matching `(api[_-]?key|secret|token|password|passwd|auth)["'\s:=]+[A-Za-z0-9_\-./+=]{16,}` (case-insensitive).
- Fire-and-forget contract:
  - The hook script must exit within 5 seconds.
  - On any internal error, swallow it and emit `{"continue": true, "suppressOutput": true}` to stdout so Claude is never blocked.
  - The script never writes to stderr in the success path; debug output is opt-in via an env var.

### Out of scope (Phase 2 / Phase 3 / never)

- `garden-recap` reading the log file. → Phase 2 (v0.8.0).
- Log retention / GC. → Phase 3 (future `garden-prune-sessions` skill or similar). Logs accumulate indefinitely in Phase 1; the directory is small (a few KB per day).
- JSONL or structured fields (diff stat, exit code). → considered if a Phase 2 consumer needs them; Phase 1 stays plain text.
- Cross-session aggregation, search index, or web viewer. → never in this plugin; that is claude-mem's domain.
- AI compression at capture time. → never; capture is a one-liner per tool call by design.
- Auto-inject into next session. → never; the vault is the user's brain, not the log.
- Vault writes. → never; the log lives outside `$KG_VAULT`.

## Behavioral Details

### Log path resolution

```
~/.local/share/knowledge-gardener/sessions/<YYYY-MM-DD>-<sid8>.log
```

- Base dir resolved as `${XDG_DATA_HOME:-$HOME/.local/share}/knowledge-gardener/sessions/`.
- The script `mkdir -p`s the base dir on first write (modes `0700` for parent, `0600` for file — same posture as supernemawashi).
- `<YYYY-MM-DD>` is **local time** at write moment, not session-start time. Crossing midnight inside one Claude session naturally splits the log into two files keyed by the same `<sid8>`. This is the desired Phase 2 behavior: a "day's recap" looks at exactly today's log, no time arithmetic needed.
- `<sid8>` = first 8 chars of `session_id` from the hook payload. If `session_id` is absent (defensive), use `unknown` so the entry still lands somewhere recoverable.

### Hook payload assumption (Claude Code spec)

`PostToolUse` payload (stdin JSON):

```jsonc
{
  "session_id": "uuid",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/...",
  "hook_event_name": "PostToolUse",
  "tool_name": "Edit",
  "tool_input":  { /* tool-specific */ },
  "tool_response": { /* tool-specific; may include success/error */ }
}
```

If the schema changes in a future Claude Code release, the script must degrade gracefully: any missing field is logged as `?` and capture continues.

### Per-tool target one-liner

The `target=` field is a short human-readable summary, **not** a faithful dump of `tool_input`. The mapping:

| Tool | `target=...` source |
|------|---------------------|
| `Edit` | basename + parent-dir of `tool_input.file_path` (e.g. `skills/garden-prune/SKILL.md`) |
| `Write` | same as `Edit` |
| `NotebookEdit` | same as `Edit` |
| `Bash` | first 80 chars of `tool_input.command`, stripped of newlines, ellipsis if truncated |
| `Agent` | `<subagent_type>:<description-first-50-chars>` |
| `mcp__<server>__<name>` | `<server>:<name>` plus optionally the first identifying arg, capped at 80 chars |
| `WebFetch` / `WebSearch` | URL or query, first 80 chars |
| Anything else not denylisted | tool name only, target = `?` |

Truncation uses a single trailing `…` (U+2026). Newlines inside `target=` are replaced with `␤` so each log entry stays on one line.

### Status field

- `status=ok` when `tool_response.success` is true or absent (most tools don't set it).
- `status=err` when `tool_response.success` is explicitly false, or when `tool_response.error` / `tool_response.is_error` is truthy.
- The hook never blocks on this; if we can't tell, omit the `[status=…]` suffix entirely.

### Privacy at the edge

Stripping happens after composing the `target=...` string, before writing. The two replacement passes:

1. `re.sub(r"<private>.*?</private>", "[REDACTED]", text, flags=re.DOTALL | re.IGNORECASE)`
2. `re.sub(r"(api[_-]?key|secret|token|password|passwd|auth)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{16,}", r"\1=[REDACTED]", text, flags=re.IGNORECASE)`

Future passes can be added without changing the log schema.

### Filter precedence

```
1. If tool_name in ALWAYS_SKIP → drop, exit 0.
2. If tool_name == "Bash":
     first_token = command.strip().split()[0]
     # strip leading `cd` and `cd <dir> &&` patterns when picking the head verb
     if first_token in BASH_TRIVIAL → drop, exit 0.
3. Compose target one-liner per the table.
4. Privacy strip.
5. Append `HH:MM tool=<Tool> target=<one-line> [status=…]\n` to the log file.
6. Print `{"continue": true, "suppressOutput": true}`, exit 0.
```

### Robustness contract

- Wrap step 5 in `try/except OSError`; on failure, swallow.
- Wrap the whole script in `try/except Exception` at the top level; on uncaught failure, still emit the continue-true payload.
- Never raise out of the script. Never write to stderr in the success path. (Stderr is reserved for debug runs.)
- Exit code is always 0.

### Performance budget

A captured entry is ~100 bytes. A busy hour of tool calls is ~200 entries = ~20 KB. A working day = ~100 KB. Python `open(..., "a")` + `write` + `close` is microseconds. The 5-second hook timeout is two orders of magnitude beyond comfortable.

## Distribution

`hooks/hooks.json` is extended (not rewritten); the new entry is added alongside the existing `SessionStart` block:

```jsonc
{
  "hooks": {
    "SessionStart": [ /* existing */ ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/capture.py\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- Plugin reload picks up the new registration automatically; no edits to `~/.claude/settings.json` are required.
- `${CLAUDE_PLUGIN_ROOT}` resolves to the per-version install dir, so an upgrade swaps the script atomically.
- `python3` is assumed to be on PATH on every supported platform. If absent the hook silently no-ops (the `command not found` exits non-zero, Claude treats that as continue with no output — verified behavior).

## File Layout (delta)

| Path | Action | Notes |
|------|--------|-------|
| `hooks/hooks.json` | Modify | Append `PostToolUse` block |
| `scripts/capture.py` | Create | Python 3, stdlib only |
| `README.md` | Modify | Mention session-log capture under a new "Phase 1: Session Capture" subsection |
| `CLAUDE.md` | Modify | Add the capture hook + script to the Architecture section |
| `package.json` / `plugin.json` / `marketplace.json` | Modify | Atomic bump `0.6.0` → `0.7.0` |

No skill files change. `garden-recap/SKILL.md` is left untouched — that is Phase 2.

## Edge Cases

- **Hook payload missing or malformed**: print `{"continue": true, "suppressOutput": true}` and exit 0. No log line written.
- **Log dir creation fails** (permission, disk full): swallow, exit 0. Capture is best-effort.
- **`session_id` field absent**: use `unknown` as the suffix so the line still lands. Phase 2 will treat `unknown` as "ungrouped".
- **Tool name not in the per-tool table** (new MCP server, new tool type): fall back to `target=?` rather than skip. Better evidence-light than no evidence.
- **Massive `tool_input.command`** (a multi-line heredoc, a 10 KB script): truncate to 80 chars, append `…`.
- **Binary or non-UTF-8 content in tool_input**: Python's default str ops handle this; we only need to display, not preserve. Replace undecodable bytes with `?` during target composition.
- **Concurrent sessions writing to the same log file**: should never happen — `<sid8>` partitions per session. If by collision two sessions land in the same file, append-mode writes are still atomic at the OS level for entries under PIPE_BUF (~4 KB), which is well above our entry size. Acceptable risk.
- **User has `XDG_DATA_HOME` set to a non-standard path**: respected. Falls back to `~/.local/share` when unset.
- **Claude Code on Windows**: out of scope for v0.7.0. The script uses `os.path.expanduser` and `os.environ`, which work on Windows in principle, but no testing matrix yet. Defer to a later release.

## Privacy / safety re-statement

- No raw tool output is captured. Only a one-line summary of `tool_input` is logged.
- Edit and Write log the file path, not the diff or contents.
- Bash logs only the first 80 chars of the command, not stdout/stderr.
- Privacy strip catches the most common foot-guns (`<private>` markers, `KEY=...` shapes).
- Logs live under the user's home dir with `0700`/`0600` modes. Not synced to git, not synced to the vault, not transmitted anywhere.

## Release Checklist (v0.7.0)

1. New `scripts/capture.py` per this design.
2. Update `hooks/hooks.json` to add the `PostToolUse` registration alongside the existing `SessionStart`.
3. Add a "Phase 1: Session Capture" subsection to `README.md` explaining the log path and what is captured.
4. Update `CLAUDE.md` Architecture section to mention the capture hook + script.
5. Bump `package.json` / `.claude-plugin/plugin.json` / `.claude-plugin/marketplace.json` from `0.6.0` → `0.7.0` atomically.
6. Commit, tag `v0.7.0`, push.

## Open questions

None for Phase 1; everything below is deferred to Phase 2.

### Phase 2 hand-off notes (for the implementer of v0.8.0)

- The log file naming convention `<YYYY-MM-DD>-<sid8>.log` is the Phase 2 consumer's input. Today's log files = `~/.local/share/knowledge-gardener/sessions/$(date +%F)-*.log`.
- `garden-recap` should read these as the source of truth when present and fall back to the existing recollection-based path when absent.
- Multi-session day: each `<sid8>` produces its own log; `garden-recap` should let the user pick one or merge by `## Session HH:MM` headings per the vault README.
- The privacy-strip pass already ran at write time; Phase 2 does not need to re-strip.

## Non-goals (re-statement)

- A general-purpose audit-log layer. Capture covers what `garden-recap` needs, nothing more.
- A replacement for Claude Code's transcript. The transcript is for Claude; the session log is for the user-facing recap.
- A queryable database. Plain text + `rg` is the search surface.
