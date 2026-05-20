# Auto-Recap on Stop (Phase 3) — Design

- **Date**: 2026-05-20
- **Status**: Approved
- **Target release**: knowledge-gardener v0.10.0
- **Source RFP**: [GitHub issue #1](https://github.com/Kohei-Wada/knowledge-gardener/issues/1)
- **Phase**: 3 of 3
- **Prior art**: [2026-05-18-session-capture-design.md](2026-05-18-session-capture-design.md) (Phase 1), [2026-05-20-recap-aggregator-design.md](2026-05-20-recap-aggregator-design.md) (Phase 2)

## Goal

Eliminate the manual "wrap up" invocation. When the user finishes interacting with Claude (Stop event), the plugin **silently writes today's session block** to the vault's daily note: it spawns a headless Claude subprocess to compose the recap from the session log + vault conventions, then `git commit && git push` the result. No user touch required.

## Why split from Phase 2

Phase 2 made `garden-recap` evidence-driven but still **user-invoked**. Phase 3 removes the invocation step. The split exists because Phase 3 introduces meaningful new dependencies (a headless Claude subprocess, vault write/commit/push from a hook, an env-var opt-in gate) that warranted soaking Phase 1+2 first.

## Scope (v0.10.0)

### In scope

- New `Stop` hook entry in `hooks/hooks.json`, calling `scripts/auto_recap.py`.
- `scripts/auto_recap.py` orchestrator (Python stdlib + `subprocess`):
  - Reads today's session log via `recap_aggregate.py`
  - Loads the vault README and daily-note template to know the format contract
  - Spawns headless Claude (`claude -p`) with a prompt template + collected context
  - Receives a markdown session-block from Claude
  - Inserts or updates a session block in today's daily note (idempotent per session_id)
  - `git add` + `git commit` + `git push` from the vault repo
- `scripts/auto_recap_prompt.md` — the prompt template fed to headless Claude.
- Env-var opt-in gate (`KG_AUTO_RECAP=1`); when unset, the hook exits 0 immediately as a no-op.
- Tests with a mocked `claude` binary (override via `KG_AUTO_RECAP_CLAUDE_CMD`).

### Out of scope (won't ship in v0.10.0)

- Auto-pruning of old session logs (still future `garden-prune-sessions`).
- A separate Anthropic API key path. We rely on the existing `claude` CLI on PATH, which already carries the user's auth.
- Cross-day rollups, weekly digests.
- Approval prompts / nudges. The user's explicit decision is "git can roll it back, don't gate it".

## Design

### Trigger

`Stop` hook with matcher `""` (no matcher → all Stop events). Stop fires when Claude finishes responding. With `/clear` and `/compact`, the session_id stays the same — each Stop within one session yields the same `<sid8>` log file. Idempotency (re-run produces the same recap block, replaced in place) is the design's escape hatch for multi-Stop-per-session.

### Opt-in

The hook does nothing unless `KG_AUTO_RECAP=1` is set in the user's shell environment when Claude Code launches. Rationale:

- The plugin is OSS; default-on auto-commit-and-push to a vault would surprise users with shared / non-disposable vaults.
- For the single-user-private-vault case (the original requester's setup), one shell line opts in.
- Other future opt-ins (`KG_AUTO_RECAP_NO_PUSH=1` to commit but not push, `KG_AUTO_RECAP_MODEL=...` to swap models) can hang off the same gate.

### Orchestrator (`scripts/auto_recap.py`)

```
1. Read hook payload from stdin (JSON). Extract session_id (→ sid8) and cwd.
2. If KG_AUTO_RECAP != "1": print continue payload, exit 0.
3. Resolve $KG_VAULT. If unset: continue payload, exit 0 (cannot write).
4. Find today's session log: $XDG_STATE_HOME/knowledge-gardener/sessions/<today>-<sid8>.log.
   If missing or empty: continue payload, exit 0 (nothing to summarize).
5. Run scripts/recap_aggregate.py --sid <sid8> to get the structured summary.
6. Load:
   - $KG_VAULT/README.md (and parent README.md)
   - the daily-note template (path declared in the README; fall back to common defaults if README is silent)
   - today's existing daily note, if any
7. Compose prompt by substituting placeholders in scripts/auto_recap_prompt.md.
8. Spawn `claude -p <prompt>` with a 120s timeout (override-able via env).
   - Cmd resolvable via $KG_AUTO_RECAP_CLAUDE_CMD (default: `claude`).
9. Parse Claude's stdout: expect a markdown block starting with `<!-- kg-recap-sid:<sid8> -->`.
10. Insert-or-replace logic on today's daily note:
    - If the marker exists in the file: replace the block between the opening and closing markers.
    - Else: append the new block before any "## Try のキャリーオーバー" style trailing section (locate via README convention), or at the end of file.
11. Run `pre-commit run --files <daily-note>` in the vault repo. If it auto-fixes, re-stage. If it errors, exit 0 without commit (best-effort).
12. `git add`, `git commit -m "water: <date> daily auto-recap (sid:<sid8>)"`, `git push`.
    - If push fails (no network / conflict): commit stays local, log the failure to a `~/.local/state/knowledge-gardener/auto-recap.log` for human follow-up.
13. Always finish with `{"continue": true, "suppressOutput": true}` on stdout. Always exit 0.
```

### Prompt template (`scripts/auto_recap_prompt.md`)

The prompt instructs Claude to:

- Output **only** a single markdown block, bounded by HTML comment markers `<!-- kg-recap-sid:<sid8> -->` and `<!-- /kg-recap-sid:<sid8> -->`.
- Follow the daily-note template's section conventions (KPT, etc.) from the README.
- Use Japanese (or whatever language the vault README declares for note bodies).
- Pick learnings / Try items from the conversation context implied by the aggregator output and the existing daily note.
- Refuse to include anything that wasn't in the aggregator output or the existing daily note. No invention.

Headless Claude doesn't see the live session's conversation history. Mitigation: feed it (a) the aggregator output (deterministic facts), (b) the existing daily note (today's prior sessions for cross-reference), (c) the vault README (format contract). Learnings & decisions will be **inferred from the actions Claude sees in the log** — they will be less rich than a Claude that saw the live conversation, but better than nothing.

### Idempotency

Session blocks are keyed by `<sid8>` via HTML comment markers:

```markdown
<!-- kg-recap-sid:abc12345 -->
## Session HH:MM 〜 <topic>

…body…

<!-- /kg-recap-sid:abc12345 -->
```

Repeated Stop firings within the same Claude session find these markers and replace the contained block instead of appending. This handles `/clear` (Stop fires, then SessionStart with same sid stays — or new sid; both are correct paths) and the natural mid-session Stop after every assistant response.

To reduce churn from hyper-frequent Stop firings: the orchestrator should **debounce** — read the existing block's timestamp marker, skip re-running Claude if the last successful recap was < 60s ago. Implement via a `.last-recap-<sid8>` file in `$XDG_STATE_HOME/knowledge-gardener/sessions/`.

### Failure modes

| Failure | Behavior |
|---------|----------|
| `KG_AUTO_RECAP` unset | exit 0, continue payload, no-op |
| `KG_VAULT` unset | exit 0, no-op |
| No session log file | exit 0, no-op (capture hook hasn't run yet) |
| Empty session log | exit 0, no-op (nothing to summarize) |
| `claude -p` exits non-zero | exit 0, log to auto-recap.log, no vault write |
| `claude -p` exceeds timeout | terminate subprocess, exit 0, log |
| Output doesn't contain expected markers | exit 0, log, no vault write |
| pre-commit fails | exit 0, log, no commit |
| `git commit` fails | exit 0, log |
| `git push` fails | commit stays local, log, exit 0 |
| File write fails (permissions, disk full) | exit 0, log |

Goal: **Claude Code is never blocked**; the worst case for the user is "auto-recap silently didn't run, check the log".

### Cost considerations

- Each Stop with a non-empty new log → one `claude -p` call. Token cost is bounded: prompt is template (~500 tokens) + aggregator output (~500 tokens) + daily-note context (≤2000 tokens). Output is bounded ~1000 tokens.
- With debounce ≥60s, a busy 8-hour session yields ~30-50 calls. Acceptable.
- Without debounce, every assistant turn fires Stop and could rack up calls.

### Distribution

`hooks/hooks.json` gains:

```jsonc
{
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/auto_recap.py\"",
          "timeout": 180
        }
      ]
    }
  ]
}
```

No matcher → fires on every Stop. The hook itself does the opt-in gate.

## File layout (delta)

| Path | Action | Notes |
|------|--------|-------|
| `scripts/auto_recap.py` | Create | Python stdlib only |
| `scripts/auto_recap_prompt.md` | Create | Prompt template |
| `tests/test_auto_recap.py` | Create | Subprocess + mock `claude` binary |
| `hooks/hooks.json` | Modify | Add `Stop` block |
| `skills/garden-recap/SKILL.md` | Modify | Note that auto-recap may have already written; explicit invocation now updates / overrides |
| `README.md` | Modify | Document `KG_AUTO_RECAP=1` opt-in |
| `CLAUDE.md` | Modify | Architecture: list Stop hook |
| `package.json` / `plugin.json` / `marketplace.json` | Bump | `0.9.0` → `0.10.0` |

## Release Checklist (v0.10.0)

1. New `scripts/auto_recap.py` and `scripts/auto_recap_prompt.md` per this design.
2. New `tests/test_auto_recap.py` covering: env-gate off, missing log, missing vault, missing claude binary, mocked claude success path, idempotent re-run, malformed output, debounce.
3. Update `hooks/hooks.json` to add the `Stop` block.
4. Update `README.md` and `CLAUDE.md` to document the opt-in mechanism.
5. Bump version atomically.
6. Commit, tag `v0.10.0`, push.
