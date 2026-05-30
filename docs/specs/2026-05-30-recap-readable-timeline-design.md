# Recap: readable Timeline with AI activity-log + mechanical fallback

Date: 2026-05-30
Status: Design (approved direction)
Related: #1 (recap pipeline), #18/#24 (two-layer block), `docs/specs/2026-05-20-auto-recap-design.md`

## Problem

The `### Timeline` written into the daily note is a verbatim, per-minute dump of
every captured tool call. For research-heavy sessions this is unusable:

- `WebFetch`/`WebSearch` emit one chunk per call — a single minute can hold 70+
  truncated URLs / queries on one line.
- `StructuredOutput` (an internal agent mechanism, not user activity) is listed
  one chunk per occurrence.
- Read-only navigation (`Read`/`Grep`/`Glob`) is listed per call.

A single Roomba-research session (`5f0a50a6`, 2026-05-30) produced a Timeline of
hundreds of lines / ~30 KB. The note is too noisy to read or to use as raw
material for a daily report (日報) — which is the user's stated reason for
keeping a Timeline at all.

### The history lesson

The very first auto-recap (`5f94704`) had the LLM compose the **entire** block —
topic + prose summary + Keep/Problem/Try — with **no deterministic Timeline
section**. The session's time record existed only inside the LLM's prose. When
the LLM call failed (the `auto-recap.log` shows dozens of consecutive
`OSError(7, 'Argument list too long')` on 2026-05-23/05-25, and `TimeoutExpired`
on 2026-05-30), nothing was written and the session's record vanished. The
project later added a deterministic `### Timeline` (#12, #18/#24) specifically to
decouple the time record from the LLM.

The current code still has a partial form of this bug: for *substantive* Stops it
calls the LLM and does `if not out: return` (`recap/autorecap/__main__.py:151-153`)
**before** writing the block — so an LLM failure drops the Timeline too.

Any fix that hands Timeline composition to the LLM without a guaranteed
deterministic fallback re-introduces the original data-loss bug.

## Goal

A Timeline that is:

1. **Readable** — grouped by activity, free of internal-mechanism noise, usable
   as 日報 raw material.
2. **Never lost** — the time record is always written, independent of LLM
   availability.

## Design

### Precedent: `build_commit_subject`

`recap/autorecap/daily_note.py:14-26` already implements the exact pattern we
want, for the commit subject:

```python
def build_commit_subject(today, start_hhmm, topic, marker_key):
    if topic is None:                                            # LLM produced no KPT
        return f"water: {today} daily auto-recap ({marker_key})" # mechanical fallback
    return f"water: {today} {start_hhmm} 〜 {topic}"             # LLM-derived
```

LLM-derived value when available; deterministic fallback otherwise. This design
applies the same pattern to the Timeline slot.

### Block structure

```
<!-- kg-recap-sid:{sid8} -->
## Session HH:MM〜HH:MM  <topic | mechanical fallback>

### Timeline
<AI activity log>            ← when the LLM succeeds
  -- OR --
<deterministic filtered timeline>   ← when the LLM fails / is not called

### KPT                      ← best-effort; omitted on LLM failure
- Keep: …
- Problem: …
- Try: …
<!-- /kg-recap-sid:{sid8} -->
```

The Timeline slot holds exactly **one** representation at a time:

- **LLM success** → AI-composed activity log (grouped by activity, time-ranged,
  semantic — e.g. `23:03–23:19 deep-research で Roomba i7 のマップ取得可否を調査
  (Web検索38件・fetch45件、dorita980 #148 等)`).
- **LLM failure / non-substantive Stop** → deterministic filtered timeline (see
  Filter rules). Short but complete; the time record is never empty.

The topic line already falls back mechanically via `build_commit_subject` — no
change there. KPT remains best-effort (LLM only), omitted on failure.

### Filter rules (deterministic timeline)

Modify `recap/aggregate/__main__.py` `_summarize_minute` so the deterministic
timeline is readable on its own. The `mcp__*` branch (collapse to `MCP server×n`)
is the model:

| Tool | Current | New |
|------|---------|-----|
| `StructuredOutput` | listed per call (`else` branch) | **dropped** (internal mechanism, not activity) |
| `WebFetch` / `WebSearch` | one chunk per call | **collapsed to `Web×N`** per minute |
| `Read` / `Grep` / `Glob` (read-only nav) | listed per call (`else`) | **collapsed to `<Tool>×N`** per minute |
| `Bash` | `Bash: <target>` | unchanged |
| `Edit` / `Write` / `NotebookEdit` | `<Tool> <path> ×n` | unchanged |
| `Agent` | `Agent→<sub>` | unchanged |
| `mcp__*` | `MCP server×n` | unchanged |
| other unknown tools | listed per call (`else`) | **collapsed to `<Tool>×N`** (count, not per-call) |

The semantic "what" (e.g. *what* was researched) is the AI layer's job; the
deterministic layer guarantees "when / how much / which tools".

### Merge model: regenerate-and-replace (not append)

Today the Timeline is aggregated `--since` the per-session cursor (incremental)
and append-merged with exact-line dedup + chronological sort
(`recap/autorecap/block.py:83-91`). AI prose and mechanical lines cannot
dedup against each other, so a session that flip-flops between LLM-success and
LLM-failure across Stops would produce a mixed, incoherent Timeline.

Change to **regenerate the whole-session Timeline on each Stop and replace** the
block's Timeline (same lifecycle as KPT):

- Aggregate the **whole-session** timeline (drop `--since` for the timeline
  input). The transcript slice for KPT stays `--since` (unchanged).
- On a substantive Stop, feed the whole-session deterministic timeline (+ prior
  AI timeline) to the LLM; it returns the regenerated AI activity log + KPT.
- Write by **replacing** the Timeline section, not merging.
- On LLM failure / non-substantive Stop, write the whole-session deterministic
  filtered timeline (replace).

Consequence: the Timeline is always coherent — either fully AI or fully
mechanical for the latest whole-session state. `block.py`'s append-merge /
dedup / sort logic for the Timeline is removed and simplified to a
replace, matching the existing KPT-replace path. Worst case (a late Stop is the
first to fail) reverts the prose to mechanical, but the time record stays
**complete** — never empty.

### Resilience fix

Remove the early `if not out: return` (`recap/autorecap/__main__.py:151-153`).
On LLM failure, fall through and write the deterministic block (filtered
timeline, mechanical topic, no KPT). The LLM result only *upgrades* the Timeline
and adds the KPT; it never gates the block.

### Both writers

The filter lives in the shared `recap/aggregate/__main__.py`, so both writers
benefit from one change:

- **auto** (`recap/autorecap/`, headless LLM): prompt extended to emit a
  `### Timeline` activity log in addition to `### KPT`; deterministic fallback as
  above.
- **manual** (`recap/manual_recap/`, assistant authors): the `garden-recap`
  skill authors the activity-log Timeline + KPT directly (the assistant *is* the
  LLM, so the fallback path is only reached if the assistant declines to author a
  Timeline, in which case the deterministic filtered timeline is written).

## Components touched

- `recap/aggregate/__main__.py` — `_summarize_minute` filter rules; ensure
  whole-session aggregation is available to callers (timeline not `--since`-gated).
- `recap/autorecap/session_aggregator.py` — request whole-session timeline for
  the block; keep `--since` only for the transcript slice.
- `recap/autorecap/block.py` — Timeline becomes replace (drop append-merge /
  dedup / sort for the Timeline section).
- `recap/autorecap/__main__.py` — remove `if not out: return`; always write the
  deterministic block, upgrade with LLM output when present.
- `recap/autorecap/prompts/auto_recap_compose_prompt.md` and
  `auto_recap_prompt.md` — emit `### Timeline` activity log + `### KPT`; strict
  output contract; facts-only / no invented links rules retained.
- `recap/manual_recap/__main__.py` — accept an authored Timeline section
  (alongside the existing `--kpt-file`); deterministic fallback when absent.
- `skills/garden-recap/SKILL.md` — author the activity-log Timeline as well as
  the KPT.

## Data flow

```
capture log (jsonl, per tool call)
   │  recap/aggregate  (whole-session)
   ▼
deterministic filtered timeline  ──────────────┐ (always available)
   │                                            │
   ├─ substantive Stop ─► LLM (prompt) ─► AI Timeline + KPT
   │                          │ success            │
   │                          │ failure            │
   ▼                          ▼                    ▼
block: replace Timeline (AI if success, else deterministic) + KPT (if success)
   ▼
DailyNote.apply_block → commit (build_commit_subject: topic or mechanical)
```

## Error handling

- LLM failure (timeout, non-zero exit, argv-too-long — already mitigated by
  stdin in #23): deterministic block still written; KPT omitted; mechanical
  topic.
- No capture log / empty session: unchanged (skip).
- Git commit/push failure: unchanged (logged; cursor still advanced).

## Testing

- `aggregate`: unit tests for the filter — `StructuredOutput` dropped, `Web×N`
  collapse, read-only-nav `×N` collapse, `Bash`/`Edit`/`Agent`/`mcp` preserved,
  mixed-minute ordering.
- `block`: Timeline replace (not append); applying identical inputs twice is a
  byte-level no-op; KPT-replace unchanged.
- `autorecap`: LLM-success path writes AI Timeline + KPT; LLM-failure path writes
  deterministic Timeline + no KPT + mechanical topic (regression test for the
  removed `if not out: return`).
- `manual_recap`: authored Timeline written; absent → deterministic fallback.

## Out of scope

- Changing the capture log format or what is captured.
- The `KG_AUTO_RECAP` opt-in gate, substantive thresholds, debounce.
- Historical daily notes already written (no migration; new format applies going
  forward).
- Removing the legacy `kg-recap-sid:{sid8}-{HHMM}` blocks already in notes.
