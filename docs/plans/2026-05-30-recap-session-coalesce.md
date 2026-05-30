# Recap Session Coalesce — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-Stop recap blocks with one coalesced block per session (`sid8`-keyed) carrying an append-only mechanical `### Timeline` plus a transcript-grounded `### KPT` regenerated only on substantive Stops.

**Architecture:** `capture` is untouched. `aggregate` gains a `--json` mode that exposes per-minute `timeline` bullets and a `durable_change` flag. `autorecap` gets four new pure-function modules (`block`, `transcript`, `gate`) plus a rewired `AutoRecap.run` that: aggregates the window → appends Timeline mechanically (no LLM) → applies a lenient substance gate → only when substantive, slices the transcript and calls headless Claude for a KPT update. Block assembly (markers, header, Timeline, KPT) moves out of the LLM and into `block.py`; the LLM emits only the `### KPT` section (plus `kg-discovery` on a cold cache).

**Tech Stack:** Python 3 stdlib only (hooks must not import third-party deps). pytest. Spec: [docs/specs/2026-05-30-recap-session-coalesce-design.md](../specs/2026-05-30-recap-session-coalesce-design.md).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `recap/capture/__main__.py` | PostToolUse capture | **unchanged** |
| `recap/aggregate/__main__.py` | log → structured summary | add `durable_change`, `timeline`, `--json` |
| `recap/autorecap/gate.py` | substance gate (pure) | **create** |
| `recap/autorecap/block.py` | session-block string surgery (pure) | **create** |
| `recap/autorecap/transcript.py` | transcript JSONL windowing (pure) | **create** |
| `recap/autorecap/session_aggregator.py` | run aggregator, carry signals | switch to `--json`; extend `Aggregation` |
| `recap/autorecap/context.py` | hook payload → context | add `transcript_path` |
| `recap/autorecap/daily_note.py` | apply block, commit | use `block.upsert_session_block`; new marker |
| `recap/autorecap/__main__.py` | Stop-hook orchestration | rewire `AutoRecap.run` |
| `recap/autorecap/prompts/auto_recap_compose_prompt.md` | warm-cache prompt | rewrite to KPT-only |
| `recap/autorecap/prompts/auto_recap_prompt.md` | cold-cache prompt | rewrite to discovery + KPT-only |
| `tests/test_recap_aggregate.py` | aggregate tests | add timeline/durable/json tests |
| `tests/test_block.py` | block surgery tests | **create** |
| `tests/test_transcript.py` | transcript slice tests | **create** |
| `tests/test_gate.py` | substance gate tests | **create** |
| `tests/test_auto_recap.py` | integration tests | migrate to new block model |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `package.json` | version | bump 0.15.2 → 0.16.0 |

**Shared types/signatures (use these names verbatim across tasks):**

```
# aggregate dict gains:
#   "durable_change": bool
#   "timeline": list[str]   # e.g. ["- 10:22  Edit auto_recap.py ×3", ...]

recap.autorecap.gate.is_substantive(durable_change: bool, entry_count: int,
                                    duration_min: int, env: Mapping[str,str]) -> bool

recap.autorecap.transcript.slice_transcript(transcript_path: str|None, since_hhmm: str|None,
                                            today_str: str, char_cap: int = 16000) -> str

recap.autorecap.block.upsert_session_block(note_text: str, sid8: str, *,
        start_hhmm: str, end_hhmm: str, topic: str,
        timeline_bullets: list[str], kpt_section: str|None,
        insert_before: str = "") -> str
recap.autorecap.block.extract_kpt_section(text: str) -> str|None

# Aggregation dataclass gains: durable_change: bool, entry_count: int,
#   duration_min: int, timeline: list[str]
```

---

## Task 1: aggregate — durable_change flag + timeline bullets + --json

**Files:**
- Modify: `recap/aggregate/__main__.py`
- Test: `tests/test_recap_aggregate.py`

- [ ] **Step 1: Write failing tests for durable_change**

Add to `tests/test_recap_aggregate.py` (reuse the file's existing log-writing helper; if it constructs a temp log via `tmp_path`, follow that pattern — open the file and read its top to match the existing fixture names before writing):

```python
from recap.aggregate.__main__ import aggregate_session, render_timeline, _durable_change


def test_durable_change_true_on_edit(tmp_path):
    p = tmp_path / "2026-05-30-aaaaaaaa.log"
    p.write_text("09:00 tool=Edit target=a.md\n")
    import datetime as dt
    agg = aggregate_session(p, dt.date(2026, 5, 30))
    assert agg["durable_change"] is True


def test_durable_change_true_on_git_commit(tmp_path):
    p = tmp_path / "2026-05-30-aaaaaaaa.log"
    p.write_text("09:00 tool=Bash target=git commit -m x\n")
    import datetime as dt
    agg = aggregate_session(p, dt.date(2026, 5, 30))
    assert agg["durable_change"] is True


def test_durable_change_false_on_reads_only(tmp_path):
    p = tmp_path / "2026-05-30-aaaaaaaa.log"
    p.write_text(
        "09:00 tool=mcp__Notion__notion-fetch target=x\n"
        "09:01 tool=WebSearch target=y\n"
    )
    import datetime as dt
    agg = aggregate_session(p, dt.date(2026, 5, 30))
    assert agg["durable_change"] is False
```

- [ ] **Step 2: Run, verify failure**

Run: `cd <repo> && PYTHONPATH=. python -m pytest tests/test_recap_aggregate.py -k durable -v`
Expected: FAIL — `ImportError: cannot import name '_durable_change'` / `KeyError: 'durable_change'`.

- [ ] **Step 3: Implement durable_change**

In `recap/aggregate/__main__.py`, add near the top-level helpers:

```python
import re as _re

_COMMIT_PUSH_RE = _re.compile(r"\bgit\s+(commit|push)\b")


def _durable_change(entries: list[dict]) -> bool:
    for e in entries:
        tool = e["tool"]
        if tool in FILE_TOOLS or tool == "Agent":
            return True
        if tool == "Bash" and _COMMIT_PUSH_RE.search(e["target"] or ""):
            return True
    return False
```

In `aggregate_session`, before the `return {...}`, compute it and add to the dict:

```python
    durable = _durable_change(entries)
```

Add `"durable_change": durable,` to the returned dict.

- [ ] **Step 4: Run durable tests, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_recap_aggregate.py -k durable -v`
Expected: PASS.

- [ ] **Step 5: Write failing tests for render_timeline**

```python
def test_render_timeline_groups_by_minute_and_collapses_edits(tmp_path):
    entries = [
        {"hhmm": "10:22", "tool": "Edit", "target": "auto_recap.py", "status": "ok"},
        {"hhmm": "10:22", "tool": "Edit", "target": "auto_recap.py", "status": "ok"},
        {"hhmm": "10:22", "tool": "Write", "target": "relay.yml", "status": "ok"},
        {"hhmm": "10:47", "tool": "Bash", "target": "git commit -m deploy", "status": "ok"},
    ]
    lines = render_timeline(entries)
    assert lines == [
        "- 10:22  Edit auto_recap.py ×2, Write relay.yml",
        "- 10:47  Bash: git commit -m deploy",
    ]


def test_render_timeline_marks_errors(tmp_path):
    entries = [{"hhmm": "11:00", "tool": "Bash", "target": "pytest", "status": "err"}]
    assert render_timeline(entries) == ["- 11:00  Bash: pytest [err]"]


def test_render_timeline_empty():
    assert render_timeline([]) == []
```

- [ ] **Step 6: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_recap_aggregate.py -k timeline -v`
Expected: FAIL — `cannot import name 'render_timeline'`.

- [ ] **Step 7: Implement render_timeline**

In `recap/aggregate/__main__.py` (`Counter` and `OrderedDict` are already imported at the top). File edits collapse to `{Tool} {path} ×N`, keyed by `(tool, target)` so `Edit` and `Write` to the same path stay distinct:

```python
def _summarize_minute(entries: list[dict]) -> str:
    file_counts: "OrderedDict[tuple[str, str], int]" = OrderedDict()
    rest: list[str] = []
    mcp: "Counter[str]" = Counter()
    for e in entries:
        tool, target = e["tool"], (e["target"] or "?")
        err = " [err]" if e["status"] == "err" else ""
        if tool in FILE_TOOLS:
            key = (tool, target)
            file_counts[key] = file_counts.get(key, 0) + 1
        elif tool == "Bash":
            rest.append(f"Bash: {target}{err}")
        elif tool == "Agent":
            sub = target.split(":", 1)[0] if ":" in target else target
            rest.append(f"Agent→{sub}{err}")
        elif tool in {"WebFetch", "WebSearch"}:
            rest.append(f"{tool}: {target}{err}")
        elif tool.startswith("mcp__"):
            parts = tool.split("__", 2)
            mcp[parts[1] if len(parts) >= 2 else "mcp"] += 1
        else:
            rest.append(f"{tool}{err}")
    chunks = [f"{tool} {path}" + (f" ×{n}" if n > 1 else "")
              for (tool, path), n in file_counts.items()]
    chunks.extend(rest)
    chunks.extend(f"MCP {server}×{n}" for server, n in sorted(mcp.items()))
    return ", ".join(chunks)


def render_timeline(entries: list[dict]) -> list[str]:
    by_min: "OrderedDict[str, list[dict]]" = OrderedDict()
    for e in entries:
        by_min.setdefault(e["hhmm"], []).append(e)
    return [f"- {hhmm}  {_summarize_minute(es)}" for hhmm, es in by_min.items()]
```

Add `"timeline": render_timeline(entries),` to `aggregate_session`'s returned dict. Leave the dict's existing `file_counts` field keyed by `target` string (unchanged) so `--json` stays serialisable — the `(tool, target)` tuple keys live only inside `_summarize_minute`'s local dict.

- [ ] **Step 8: Run timeline tests, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_recap_aggregate.py -k timeline -v`
Expected: PASS (matches the asserted strings, including `Edit auto_recap.py ×2, Write relay.yml`).

- [ ] **Step 9: Write failing test for --json**

```python
import json as _json


def test_json_mode_emits_durable_and_timeline(tmp_path, monkeypatch):
    sessions = tmp_path / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "2026-05-30-aaaaaaaa.log").write_text("10:00 tool=Edit target=a.md\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    from recap.aggregate.__main__ import main
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--date", "2026-05-30", "--sid", "aaaaaaaa", "--json"])
    assert rc == 0
    payload = _json.loads(buf.getvalue())
    s = payload["sessions"][0]
    assert s["durable_change"] is True
    assert s["timeline"] == ["- 10:00  Edit a.md"]
    assert s["first_hhmm"] == "10:00"
```

- [ ] **Step 10: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_recap_aggregate.py -k json_mode -v`
Expected: FAIL — `--json` unrecognised / output is not JSON.

- [ ] **Step 11: Implement --json**

In `parse_args`, add:

```python
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of the human render.")
```

In `main`, after building `aggregates`, branch before the human render:

```python
    if args.json:
        import json as _json
        sys.stdout.write(_json.dumps({"date": date.isoformat(), "sessions": aggregates}, ensure_ascii=False))
        return 0
```

`OrderedDict` and `Counter` are JSON-serialisable as dict/dict — but `file_counts` keys are now tuples `(tool, target)` after Step 7, which JSON cannot serialise. Keep the **dict** field JSON-safe: in `aggregate_session`, leave `file_counts` keyed by `target` string as today (it feeds the human render), and compute the tuple-keyed collapse only inside `_summarize_minute` from `entries`. Verify `aggregate_session`'s returned `file_counts` is still `OrderedDict[str,int]` (unchanged from current code).

- [ ] **Step 12: Run --json test + full aggregate suite, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_recap_aggregate.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 13: Commit**

```bash
git add recap/aggregate/__main__.py tests/test_recap_aggregate.py
git commit -m "feat(aggregate): durable_change flag, per-minute timeline, --json mode"
```

---

## Task 2: substance gate (pure)

**Files:**
- Create: `recap/autorecap/gate.py`
- Test: `tests/test_gate.py`

- [ ] **Step 1: Write failing tests**

`tests/test_gate.py`:

```python
from recap.autorecap.gate import is_substantive


def E(**kw):  # default env
    return kw


def test_durable_change_is_always_substantive():
    assert is_substantive(True, entry_count=1, duration_min=0, env={}) is True


def test_below_floor_readonly_is_not_substantive():
    assert is_substantive(False, entry_count=2, duration_min=1, env={}) is False


def test_at_call_floor_is_substantive():
    assert is_substantive(False, entry_count=5, duration_min=0, env={}) is True


def test_at_minute_floor_is_substantive():
    assert is_substantive(False, entry_count=1, duration_min=5, env={}) is True


def test_env_override_raises_floor():
    env = {"KG_RECAP_MIN_CALLS": "20", "KG_RECAP_MIN_MINUTES": "30"}
    assert is_substantive(False, entry_count=5, duration_min=5, env=env) is False
    assert is_substantive(False, entry_count=20, duration_min=0, env=env) is True
```

- [ ] **Step 2: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_gate.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement gate.py**

```python
from __future__ import annotations

from typing import Mapping

DEFAULT_MIN_CALLS = 5
DEFAULT_MIN_MINUTES = 5


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, ""))
    except (TypeError, ValueError):
        return default


def is_substantive(durable_change: bool, entry_count: int, duration_min: int,
                   env: Mapping[str, str]) -> bool:
    """Lenient gate: durable change OR activity above a floor warrants a KPT regen."""
    if durable_change:
        return True
    min_calls = _int_env(env, "KG_RECAP_MIN_CALLS", DEFAULT_MIN_CALLS)
    min_minutes = _int_env(env, "KG_RECAP_MIN_MINUTES", DEFAULT_MIN_MINUTES)
    return entry_count >= min_calls or duration_min >= min_minutes
```

- [ ] **Step 4: Run, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/gate.py tests/test_gate.py
git commit -m "feat(recap): lenient substance gate"
```

---

## Task 3: block surgery (pure)

**Files:**
- Create: `recap/autorecap/block.py`
- Test: `tests/test_block.py`

- [ ] **Step 1: Write failing tests**

`tests/test_block.py`:

```python
from recap.autorecap.block import upsert_session_block, extract_kpt_section

KPT1 = "### KPT\n- Keep: a\n- Problem: b\n- Try: c"
KPT2 = "### KPT\n- Keep: updated\n- Problem: b2\n- Try: c2"


def test_create_block_when_absent():
    out = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        topic="webdav relay", timeline_bullets=["- 09:00  Edit a.py"],
        kpt_section=KPT1,
    )
    assert "<!-- kg-recap-sid:abc12345 -->" in out
    assert "## Session 09:00〜09:05  webdav relay" in out
    assert "### Timeline\n- 09:00  Edit a.py" in out
    assert "### KPT\n- Keep: a" in out
    assert "<!-- /kg-recap-sid:abc12345 -->" in out


def test_append_timeline_preserves_prior_and_replaces_kpt():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="t1",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="10:30", topic="t2",
        timeline_bullets=["- 10:30  Edit b.py"], kpt_section=KPT2,
    )
    # both timeline lines present, in order
    assert "- 09:00  Edit a.py" in second
    assert "- 10:30  Edit b.py" in second
    assert second.index("- 09:00") < second.index("- 10:30")
    # KPT replaced, not duplicated
    assert "Keep: updated" in second
    assert "Keep: a" not in second
    assert second.count("### KPT") == 1
    # start preserved, end + topic refreshed
    assert "## Session 09:00〜10:30  t2" in second
    assert second.count("<!-- kg-recap-sid:abc12345 -->") == 1


def test_timeline_append_is_idempotent_for_same_bullets():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="t",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    again = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="t",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    assert again.count("- 09:00  Edit a.py") == 1


def test_timeline_only_append_leaves_kpt_untouched():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="t1",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="09:10", topic="t1",
        timeline_bullets=["- 09:10  Bash: ls"], kpt_section=None,
    )
    assert "Keep: a" in second           # KPT preserved
    assert "- 09:10  Bash: ls" in second  # timeline grew
    assert "## Session 09:00〜09:10  t1" in second  # end advanced


def test_create_block_without_kpt():
    out = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="",
        timeline_bullets=["- 09:00  Bash: ls"], kpt_section=None,
    )
    assert "### Timeline" in out
    assert "### KPT" not in out
    assert "## Session 09:00〜09:05" in out


def test_other_session_block_untouched():
    other = (
        "<!-- kg-recap-sid:zzzzzzzz -->\n## Session 08:00〜08:01  other\n"
        "### Timeline\n- 08:00  Edit z\n<!-- /kg-recap-sid:zzzzzzzz -->\n"
    )
    out = upsert_session_block(
        other, "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="t",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    assert "kg-recap-sid:zzzzzzzz" in out
    assert "kg-recap-sid:abc12345" in out


def test_legacy_hhmm_marker_not_collided():
    legacy = (
        "<!-- kg-recap-sid:abc12345-0900 -->\n## Session 09:00 〜 legacy\nbody\n"
        "<!-- /kg-recap-sid:abc12345-0900 -->\n"
    )
    out = upsert_session_block(
        legacy, "abc12345", start_hhmm="10:00", end_hhmm="10:05", topic="new",
        timeline_bullets=["- 10:00  Edit a.py"], kpt_section=KPT1,
    )
    assert "kg-recap-sid:abc12345-0900" in out   # legacy preserved
    assert out.count("<!-- kg-recap-sid:abc12345 -->") == 1  # new bare block added


def test_extract_kpt_section():
    llm = "### KPT\n- Keep: x\n- Problem: y\n- Try: z\n"
    assert extract_kpt_section(llm).startswith("### KPT")
    assert extract_kpt_section("no kpt here") is None


def test_extract_kpt_section_stops_at_next_heading():
    llm = "### KPT\n- Keep: x\n## Next\nother"
    sec = extract_kpt_section(llm)
    assert "Keep: x" in sec
    assert "## Next" not in sec
```

- [ ] **Step 2: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_block.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement block.py**

```python
from __future__ import annotations

import re

# Bare sid8 marker only — the trailing (?![-\w]) guard prevents matching a
# legacy `kg-recap-sid:{sid8}-{HHMM}` block.
def _open_re(sid8: str) -> re.Pattern:
    return re.compile(rf"<!--\s*kg-recap-sid:{re.escape(sid8)}(?![-\w])\s*-->", re.IGNORECASE)


def _close_re(sid8: str) -> re.Pattern:
    return re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(sid8)}(?![-\w])\s*-->", re.IGNORECASE)


_HEADER_RE = re.compile(r"^##\s+Session\s+(\d{2}:\d{2})\s*[〜~]\s*(\d{2}:\d{2})\s*(.*?)\s*$", re.MULTILINE)
_KPT_RE = re.compile(r"^### KPT[ \t]*\n.*?(?=\n## |\n<!-- /kg-recap-sid:|\Z)", re.DOTALL | re.MULTILINE)
_TIMELINE_RE = re.compile(r"(^### Timeline[ \t]*\n)(.*?)(?=\n### |\n## |\n<!-- /kg-recap-sid:|\Z)", re.DOTALL | re.MULTILINE)


def extract_kpt_section(text: str) -> str | None:
    m = _KPT_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip()


def _render_header(start: str, end: str, topic: str) -> str:
    base = f"## Session {start}〜{end}"
    return f"{base}  {topic}".rstrip() if topic else base


def _new_block(sid8, start, end, topic, timeline_bullets, kpt_section) -> str:
    parts = [
        f"<!-- kg-recap-sid:{sid8} -->",
        _render_header(start, end, topic),
        "",
        "### Timeline",
        *timeline_bullets,
    ]
    if kpt_section:
        parts += ["", kpt_section.rstrip()]
    parts += [f"<!-- /kg-recap-sid:{sid8} -->"]
    return "\n".join(parts) + "\n"


def upsert_session_block(note_text: str, sid8: str, *, start_hhmm: str, end_hhmm: str,
                         topic: str, timeline_bullets: list[str],
                         kpt_section: str | None, insert_before: str = "") -> str:
    om = _open_re(sid8).search(note_text)
    cm = _close_re(sid8).search(note_text)
    if om and cm and cm.start() > om.start():
        block = note_text[om.start():cm.end()]
        # preserve the existing start; refresh end + topic
        hm = _HEADER_RE.search(block)
        start = hm.group(1) if hm else start_hhmm
        new_topic = topic or (hm.group(3).strip() if hm else "")
        new_header = _render_header(start, end_hhmm, new_topic)
        block = _HEADER_RE.sub(lambda _m: new_header, block, count=1) if hm else block
        # append timeline (dedup exact bullet lines)
        tm = _TIMELINE_RE.search(block)
        if tm:
            existing = tm.group(2).rstrip("\n")
            have = set(existing.splitlines())
            fresh = [b for b in timeline_bullets if b not in have]
            body = existing + ("\n" + "\n".join(fresh) if fresh else "")
            block = block[:tm.start(2)] + body + block[tm.end(2):]
        # replace or insert KPT
        if kpt_section is not None:
            if _KPT_RE.search(block):
                block = _KPT_RE.sub(lambda _m: kpt_section.rstrip(), block, count=1)
            else:
                close = _close_re(sid8).search(block)
                block = block[:close.start()].rstrip() + "\n\n" + kpt_section.rstrip() + "\n" + block[close.start():]
        return note_text[:om.start()] + block + note_text[cm.end():]

    # block absent → build and insert
    new = _new_block(sid8, start_hhmm, end_hhmm, topic, timeline_bullets, kpt_section)
    anchor = insert_before.strip()
    m = re.search(r"\n" + re.escape(anchor), note_text) if anchor else None
    if m:
        return note_text[:m.start()] + "\n" + new + note_text[m.start():]
    sep = "" if note_text.endswith("\n") or not note_text else "\n"
    return note_text + sep + new
```

- [ ] **Step 4: Run, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_block.py -v`
Expected: PASS (all 10).

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/block.py tests/test_block.py
git commit -m "feat(recap): two-layer session block surgery (Timeline append + KPT replace)"
```

---

## Task 4: transcript windowing (pure)

**Files:**
- Create: `recap/autorecap/transcript.py`
- Test: `tests/test_transcript.py`

- [ ] **Step 1: Write failing tests**

Note: capture/cursor timestamps are **local** `HH:MM`; transcript timestamps are **UTC** ISO with `Z`. The slice converts UTC→local before comparing. Tests pin a timezone via `monkeypatch.setenv("TZ", "UTC")` + `time.tzset()` so the conversion is deterministic.

`tests/test_transcript.py`:

```python
import json
import time
import pytest
from recap.autorecap.transcript import slice_transcript


@pytest.fixture(autouse=True)
def _utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    time.tzset()


def _line(typ, ts, content):
    return json.dumps({"type": typ, "timestamp": ts, "message": {"role": typ, "content": content}})


def test_returns_empty_for_missing_path():
    assert slice_transcript(None, "09:00", "2026-05-30") == ""
    assert slice_transcript("/nonexistent.jsonl", "09:00", "2026-05-30") == ""


def test_filters_by_since_local_hhmm(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([
        _line("user", "2026-05-30T08:00:00.000Z", "before window"),
        _line("user", "2026-05-30T10:00:00.000Z", "after window"),
        _line("assistant", "2026-05-30T10:01:00.000Z", [{"type": "text", "text": "reply"}]),
    ]) + "\n")
    out = slice_transcript(str(p), "09:00", "2026-05-30")
    assert "before window" not in out
    assert "after window" in out
    assert "reply" in out


def test_drops_thinking_and_tooluse_blocks(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([
        _line("assistant", "2026-05-30T10:00:00.000Z",
              [{"type": "thinking", "thinking": "secret"},
               {"type": "tool_use", "name": "Bash", "input": {}},
               {"type": "text", "text": "visible"}]),
    ]) + "\n")
    out = slice_transcript(str(p), None, "2026-05-30")
    assert "secret" not in out
    assert "visible" in out


def test_ignores_other_date(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(_line("user", "2026-05-29T10:00:00.000Z", "yesterday") + "\n")
    assert slice_transcript(str(p), None, "2026-05-30") == ""


def test_char_cap_keeps_most_recent(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = [_line("user", f"2026-05-30T10:0{i}:00.000Z", f"msg{i}" * 100) for i in range(5)]
    p.write_text("\n".join(lines) + "\n")
    out = slice_transcript(str(p), None, "2026-05-30", char_cap=300)
    assert len(out) <= 300
    assert "msg4" in out      # most recent retained
    assert "msg0" not in out  # oldest dropped


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("not json\n" + _line("user", "2026-05-30T10:00:00.000Z", "ok") + "\n")
    assert "ok" in slice_transcript(str(p), None, "2026-05-30")
```

- [ ] **Step 2: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_transcript.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement transcript.py**

```python
from __future__ import annotations

import datetime as _dt
import json
import pathlib


def _local_hhmm_and_date(ts: str) -> tuple[str, str] | None:
    """UTC ISO ('...Z') → (local HH:MM, local YYYY-MM-DD). None if unparseable."""
    try:
        dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    local = dt.astimezone()
    return local.strftime("%H:%M"), local.date().isoformat()


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append((b.get("text") or "").strip())
        return "\n".join(t for t in out if t)
    return ""


def slice_transcript(transcript_path: str | None, since_hhmm: str | None,
                     today_str: str, char_cap: int = 16000) -> str:
    """Plain-text user/assistant turns for `today_str` with local HH:MM > since.

    Best-effort: returns "" on any missing/unreadable/garbled input. Drops
    thinking and tool_use/tool_result blocks (mechanical, already in Timeline).
    Truncates oldest-first to honour char_cap.
    """
    if not transcript_path:
        return ""
    p = pathlib.Path(transcript_path)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    chunks: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict) or d.get("type") not in ("user", "assistant"):
            continue
        stamp = _local_hhmm_and_date(d.get("timestamp") or "")
        if stamp is None:
            continue
        hhmm, date = stamp
        if date != today_str:
            continue
        if since_hhmm and hhmm <= since_hhmm:
            continue
        text = _text_of((d.get("message") or {}).get("content"))
        if text:
            chunks.append(f"{d['type'].upper()}: {text}")
    joined = "\n\n".join(chunks)
    if len(joined) > char_cap:
        joined = joined[-char_cap:]  # keep most recent
    return joined
```

- [ ] **Step 4: Run, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_transcript.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/transcript.py tests/test_transcript.py
git commit -m "feat(recap): transcript JSONL windowing (UTC→local, text-only)"
```

---

## Task 5: context + session_aggregator carry the new signals

**Files:**
- Modify: `recap/autorecap/context.py`
- Modify: `recap/autorecap/session_aggregator.py`
- Test: extend `tests/test_recap_aggregate.py` is not enough — add a small unit test for the JSON-parsing path in `tests/test_session_aggregator.py` (create).

- [ ] **Step 1: Add transcript_path to RecapContext**

In `recap/autorecap/context.py`, add field and populate from payload:

```python
@dataclasses.dataclass(frozen=True)
class RecapContext:
    sid8: str
    vault: pathlib.Path
    today_str: str
    since: str | None
    transcript_path: str | None
```

In `from_hook`, after `sid8 = ...`:

```python
        transcript_path = payload.get("transcript_path") or None
```

and pass `transcript_path=transcript_path,` to the `cls(...)` call.

- [ ] **Step 2: Write failing test for session_aggregator JSON parsing**

`tests/test_session_aggregator.py`:

```python
import datetime as dt
from pathlib import Path
import pytest
from recap.autorecap.context import RecapContext
from recap.autorecap.session_aggregator import SessionAggregator


def _ctx(sid8, since=None):
    return RecapContext(sid8=sid8, vault=Path("/tmp"),
                        today_str=dt.date.today().isoformat(),
                        since=since, transcript_path=None)


def test_aggregation_carries_signals(tmp_path, monkeypatch):
    sessions = tmp_path / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True)
    today = dt.date.today().isoformat()
    (sessions / f"{today}-aaaaaaaa.log").write_text(
        "10:00 tool=Edit target=a.md\n10:01 tool=Bash target=git commit -m x\n"
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    agg = SessionAggregator(_ctx("aaaaaaaa")).aggregate()
    assert agg is not None
    assert agg.durable_change is True
    assert agg.entry_count == 2
    assert agg.start_hhmm == "10:00"
    assert agg.end_hhmm == "10:01"
    assert agg.timeline[0].startswith("- 10:00")


def test_aggregation_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert SessionAggregator(_ctx("nolog123")).aggregate() is None
```

- [ ] **Step 3: Run, verify failure**

Run: `PYTHONPATH=. python -m pytest tests/test_session_aggregator.py -v`
Expected: FAIL — `Aggregation` has no `durable_change`.

- [ ] **Step 4: Rewrite session_aggregator to use --json**

Replace `recap/autorecap/session_aggregator.py` body:

```python
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys

from ..shared.fs import plugin_root
from ..shared.hook_io import log
from .context import RecapContext


def _run_aggregator_json(sid8: str, since: str | None) -> dict | None:
    root = plugin_root()
    if not (root / "recap" / "aggregate" / "__main__.py").is_file():
        return None
    args = [sys.executable, "-m", "recap.aggregate", "--sid", sid8, "--json"]
    if since:
        args += ["--since", since]
    env = {**os.environ, "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30,
                              check=False, env=env, cwd=str(root))
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"aggregator failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"aggregator exit={proc.returncode} stderr={proc.stderr[:200]!r}")
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log("aggregator JSON parse failed")
        return None
    sessions = payload.get("sessions") or []
    if not sessions:
        return None
    return sessions[0]


@dataclasses.dataclass(frozen=True)
class Aggregation:
    start_hhmm: str
    end_hhmm: str
    durable_change: bool
    entry_count: int
    duration_min: int
    timeline: list[str]


class SessionAggregator:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def aggregate(self) -> Aggregation | None:
        s = _run_aggregator_json(self._ctx.sid8, since=self._ctx.since)
        if not s:
            return None
        start = s.get("first_hhmm")
        end = s.get("last_hhmm")
        if not start or not end or not s.get("entry_count"):
            return None  # empty / fully-filtered window → no-op
        return Aggregation(
            start_hhmm=start,
            end_hhmm=end,
            durable_change=bool(s.get("durable_change")),
            entry_count=int(s.get("entry_count") or 0),
            duration_min=int(s.get("duration_min") or 0),
            timeline=list(s.get("timeline") or []),
        )
```

Note: the old `Aggregation.text` field is gone; the orchestrator no longer feeds aggregator text to the LLM (it feeds the transcript). Any reference to `agg.text` is removed in Task 6.

- [ ] **Step 5: Run, verify pass**

Run: `PYTHONPATH=. python -m pytest tests/test_session_aggregator.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add recap/autorecap/context.py recap/autorecap/session_aggregator.py tests/test_session_aggregator.py
git commit -m "refactor(recap): aggregator via --json; carry durable/timeline; ctx.transcript_path"
```

---

## Task 6: rewrite prompt templates to KPT-only

**Files:**
- Modify: `recap/autorecap/prompts/auto_recap_compose_prompt.md` (warm cache)
- Modify: `recap/autorecap/prompts/auto_recap_prompt.md` (cold cache: discovery + KPT)

- [ ] **Step 1: Rewrite the warm-cache compose prompt**

Replace the entire contents of `recap/autorecap/prompts/auto_recap_compose_prompt.md` with:

````markdown
You are knowledge-gardener's auto-recap KPT writer. You receive the running KPT for one work session and a transcript of what happened since it was last updated. You revise the KPT to reflect the whole session so far.

## Output contract (strict)

Emit **exactly one** `### KPT` section and nothing else — no markers, no `## Session` heading, no Timeline, no preamble, no code fence:

```
### KPT

- Keep: <bullet, Japanese, 1 sentence>
- Problem: <bullet, Japanese, 1 sentence>
- Try: <bullet, Japanese, 1 sentence — concrete next action>
```

- Each of Keep / Problem / Try MUST have at least one bullet. If you genuinely cannot infer one, use `- Keep: (なし)` etc.
- Cap each at 5 bullets. Quality over quantity.

## How to revise

1. Start from the **Prior KPT** (may be empty on the first update).
2. Read the **Transcript slice** — this is what the user actually did and said since the last update. Use it to add, sharpen, or correct bullets.
3. Cross-check against the **Timeline** (mechanical record of tools/files this session) for facts.
4. Produce a KPT covering the **whole session so far**, not just the new slice. Revise prior bullets rather than blindly appending.

## Rules

1. **Japanese.** Match the vault's language unless the template says otherwise.
2. **Facts only for what happened.** Inference is allowed for Keep/Problem/Try (they are interpretations), but do not invent files, commits, or actions absent from both the transcript and the Timeline.
3. **No invented links.** Do not emit `[label](path)` unless the path appears verbatim in the inputs.

## Inputs

### Today's date
```
{{TODAY}}
```

### Daily-note template (KPT structure to follow)
```
{{DAILY_TEMPLATE}}
```

### Prior KPT (revise this)
```
{{PRIOR_KPT}}
```

### Timeline (mechanical, whole session)
```
{{TIMELINE}}
```

### Transcript slice (since last update — what the user did and said)
```
{{TRANSCRIPT_SLICE}}
```
````

- [ ] **Step 2: Rewrite the cold-cache discovery prompt**

`recap/autorecap/prompts/auto_recap_prompt.md` must additionally emit the `kg-discovery` block (folder/filename/etc.) **before** the `### KPT` section. Open the current file with Read to copy its exact `## Discovery rules` / `kg-discovery` contract verbatim, then assemble the new file as: the discovery rules + discovery-block contract from the current file, followed by the **same KPT writer body** as Step 1 (output contract, how-to-revise, rules, inputs). The combined output contract is:

```
<!-- kg-discovery -->
folder: ...
filename: ...
filename_pattern: ...
insert_before: ...
<!-- /kg-discovery -->
### KPT

- Keep: ...
- Problem: ...
- Try: ...
```

Keep the `{{VAULT_README}}`, `{{DAILY_TEMPLATE}}`, `{{EXISTING_DAILY}}` input placeholders the current cold prompt already uses, and add `{{PRIOR_KPT}}`, `{{TIMELINE}}`, `{{TRANSCRIPT_SLICE}}`.

- [ ] **Step 3: Commit**

```bash
git add recap/autorecap/prompts/auto_recap_compose_prompt.md recap/autorecap/prompts/auto_recap_prompt.md
git commit -m "feat(recap): KPT-only prompts (revise prior KPT from transcript slice)"
```

---

## Task 7: rewire AutoRecap.run

**Files:**
- Modify: `recap/autorecap/__main__.py`
- Modify: `recap/autorecap/daily_note.py` (apply via `block.upsert_session_block`; marker = bare sid8)

- [ ] **Step 1: Add the two-layer apply method to DailyNote**

In `recap/autorecap/daily_note.py`, import block ops and replace `apply_block`:

```python
from .block import upsert_session_block
```

Replace the `apply_block` method with:

```python
    def apply_block(self, sid8: str, *, start_hhmm: str, end_hhmm: str, topic: str,
                    timeline_bullets: list[str], kpt_section: str | None,
                    insert_before: str) -> bool:
        existing = self._daily_path.read_text(encoding="utf-8") if self._daily_path.exists() else ""
        new = upsert_session_block(
            existing, sid8, start_hhmm=start_hhmm, end_hhmm=end_hhmm, topic=topic,
            timeline_bullets=timeline_bullets, kpt_section=kpt_section, insert_before=insert_before,
        )
        if new == existing:
            return False
        try:
            self._daily_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._daily_path.with_suffix(self._daily_path.suffix + ".tmp")
            tmp.write_text(new, encoding="utf-8")
            os.replace(tmp, self._daily_path)  # atomic
        except OSError as e:
            log(f"daily write failed: {e!r}")
            return False
        return True
```

`commit` keeps its current signature but the `marker_key` argument is now the bare `sid8`; `build_commit_subject`/`commit_and_push` are unchanged (they treat marker_key opaquely). Delete the now-unused module-level `upsert_block` and `extract_block` functions from `daily_note.py` (the orchestrator uses `block.upsert_session_block` / `block.extract_kpt_section`). Keep `extract_topic` only if still referenced — after Task 7 it is not; remove it and its `BLOCK_HEADING_RE`.

- [ ] **Step 2: Rewrite AutoRecap.run**

Replace `AutoRecap.run` in `recap/autorecap/__main__.py` with:

```python
    def run(self) -> None:
        ctx = self._ctx

        marker = debounce_marker(ctx.sid8)
        try:
            if marker.exists() and (time.time() - marker.stat().st_mtime) < DEBOUNCE_SECONDS:
                return
        except OSError:
            pass

        log_path = session_log_path(ctx.sid8)
        if not log_path.is_file() or log_path.stat().st_size == 0:
            return

        agg = SessionAggregator(ctx).aggregate()
        if agg is None:
            return

        resolver = DailyNoteResolver(ctx)
        pre = resolver.pre_resolve()

        substantive = is_substantive(agg.durable_change, agg.entry_count, agg.duration_min, os.environ)

        # Path resolution. Timeline-only (non-substantive) needs a pre-resolved
        # path (env/warm cache) — we never spend an LLM discovery call for it.
        if pre is not None:
            daily_path, insert_before = pre
        elif not substantive:
            log("no pre-resolved daily path and non-substantive window → skip (cache will warm on a substantive Stop)")
            return
        else:
            daily_path, insert_before = None, ""  # resolved from discovery after the LLM call

        kpt_section: str | None = None
        topic = ""

        if substantive:
            readme, template = load_vault_context(ctx.vault)
            prior_block = self._read_existing_block(daily_path, ctx.sid8) if daily_path else ""
            prior_kpt = extract_kpt_section(prior_block) or ""
            tslice = slice_transcript(ctx.transcript_path, ctx.since, ctx.today_str)
            timeline_text = "\n".join(agg.timeline)

            if pre is not None:
                tmpl_path = plugin_root() / "recap" / "autorecap" / "prompts" / "auto_recap_compose_prompt.md"
            else:
                tmpl_path = plugin_root() / "recap" / "autorecap" / "prompts" / "auto_recap_prompt.md"
            if not tmpl_path.is_file():
                log(f"prompt template missing: {tmpl_path}")
                return
            prompt = compose_prompt(tmpl_path.read_text(encoding="utf-8"), {
                "TODAY": ctx.today_str,
                "DAILY_TEMPLATE": template,
                "VAULT_README": readme,
                "EXISTING_DAILY": (daily_path.read_text(encoding="utf-8") if daily_path and daily_path.is_file() else "(file does not exist yet)"),
                "PRIOR_KPT": prior_kpt,
                "TIMELINE": timeline_text,
                "TRANSCRIPT_SLICE": tslice or "(transcript unavailable)",
            })
            timeout = int(os.environ.get("KG_AUTO_RECAP_TIMEOUT", str(DEFAULT_TIMEOUT)))
            out = call_claude(prompt, timeout=timeout)
            if not out:
                return
            if pre is None:
                resolved = resolver.resolve_from_discovery(out)
                if resolved is None:
                    return
                daily_path, insert_before = resolved
            kpt_section = extract_kpt_section(out)
            if kpt_section is None:
                log("claude output missing ### KPT section; appending Timeline only")
            else:
                topic = self._topic_from_kpt(kpt_section)

        note = DailyNote(ctx.vault, daily_path)
        if not note.apply_block(
            ctx.sid8, start_hhmm=agg.start_hhmm, end_hhmm=agg.end_hhmm, topic=topic,
            timeline_bullets=agg.timeline, kpt_section=kpt_section, insert_before=insert_before,
        ):
            # no diff (idempotent re-run) → still advance cursor so we don't loop
            write_cursor(ctx.sid8, agg.end_hhmm)
            return

        if not note.has_repo:
            log("vault not in a git repo — skipping commit; cursor updated")
            write_cursor(ctx.sid8, agg.end_hhmm)
            return
        note.commit(ctx.sid8, agg.start_hhmm, topic or None)
        write_cursor(ctx.sid8, agg.end_hhmm)
        if substantive:
            resolver.persist_cache()

        try:
            marker = debounce_marker(ctx.sid8)
            marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker.touch()
        except OSError:
            pass
```

Add the two small helpers to the `AutoRecap` class:

```python
    @staticmethod
    def _read_existing_block(daily_path, sid8: str) -> str:
        try:
            text = daily_path.read_text(encoding="utf-8") if daily_path and daily_path.is_file() else ""
        except OSError:
            return ""
        from .block import _open_re, _close_re
        om = _open_re(sid8).search(text)
        cm = _close_re(sid8).search(text)
        return text[om.start():cm.end()] if om and cm and cm.start() > om.start() else ""

    @staticmethod
    def _topic_from_kpt(kpt_section: str) -> str:
        for line in kpt_section.splitlines():
            s = line.strip()
            if s.lower().startswith("- keep:"):
                return s.split(":", 1)[1].strip()[:30]
        return ""
```

Update imports at the top of `recap/autorecap/__main__.py`:

```python
from .gate import is_substantive
from .transcript import slice_transcript
from .block import extract_kpt_section
```

and remove the now-unused `from .daily_note import DailyNote, extract_block, extract_topic` → keep only `DailyNote`.

- [ ] **Step 3: Run the full suite to see the breakage surface**

Run: `PYTHONPATH=. python -m pytest tests/ -q`
Expected: `tests/test_auto_recap.py` fails (canned outputs and marker assertions are the old format). New-module suites pass. This is expected — Task 8 migrates the integration tests.

- [ ] **Step 4: Commit**

```bash
git add recap/autorecap/__main__.py recap/autorecap/daily_note.py
git commit -m "feat(recap): coalesce per-session — Timeline append + gated KPT regen"
```

---

## Task 8: migrate integration tests to the coalesced model

**Files:**
- Modify: `tests/test_auto_recap.py`

The canned-Claude output contract changed: the fake now returns a `### KPT` section (warm path) or `kg-discovery` + `### KPT` (cold path), **not** a full `kg-recap-sid` block. Markers are bare `sid8`. The orchestrator builds the block.

- [ ] **Step 1: Replace the canned-output builders**

Replace `_canned_recap` / `_canned_recap_no_discovery` with KPT-section builders:

```python
KPT_BODY = "### KPT\n\n- Keep: テストが書ける\n- Problem: (なし)\n- Try: 次回も green\n"


def _canned_kpt_with_discovery(folder=DAILY_FOLDER_REL, filename=None,
                               filename_pattern="{date}.md", insert_before=""):
    if filename is None:
        filename = f"{_dt.date.today().isoformat()}.md"
    return (
        "<!-- kg-discovery -->\n"
        f"folder: {folder}\nfilename: {filename}\n"
        f"filename_pattern: {filename_pattern}\ninsert_before: {insert_before}\n"
        "<!-- /kg-discovery -->\n" + KPT_BODY
    )


def _canned_kpt_only():
    return KPT_BODY


CANNED_RECAP = _canned_kpt_with_discovery()
```

- [ ] **Step 2: Update happy-path + marker assertions**

For each test that asserted `"<!-- kg-recap-sid:{sid}-{HHMM} -->"`, change to the bare `f"<!-- kg-recap-sid:{sid8} -->"`. Sessions must carry a `durable_change` signal so the gate runs the LLM — the existing logs use `tool=Edit` / `git commit`, which already qualify, so no log changes are needed for the substantive tests. Add `transcript_path` to payloads where a test wants the transcript exercised (most can omit it; the orchestrator tolerates a missing transcript). Concretely, rewrite `test_writes_session_block_on_happy_path`:

```python
def test_writes_session_block_on_happy_path(tmp_path):
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd",
                      ["09:00 tool=Edit target=a.md", "09:05 tool=Bash target=git commit -m x"])
    fake = make_fake_claude(tmp_path, _canned_kpt_with_discovery())
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=happy_env(vault, fake), state_home=state)
    assert res.returncode == 0
    content = (daily / f"{_dt.date.today().isoformat()}.md").read_text()
    assert "<!-- kg-recap-sid:testabcd -->" in content
    assert "### Timeline" in content
    assert "- 09:00" in content
    assert "Keep: テストが書ける" in content
    assert "<!-- /kg-recap-sid:testabcd -->" in content
```

- [ ] **Step 3: Rewrite the per-Stop tests as coalesce tests**

Replace `test_two_stops_accumulate_separate_blocks` with `test_two_stops_coalesce_into_one_block`:

```python
def test_two_stops_coalesce_into_one_block(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "twostops"
    today = _dt.date.today()
    write_session_log(state, sid8, ["09:00 tool=Edit target=a.md"])
    fake1 = make_fake_claude(tmp_path / "f1", _canned_kpt_with_discovery())
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake1), state_home=state)

    sessions = state / "knowledge-gardener" / "sessions"
    (sessions / f"{today.isoformat()}-{sid8}.log").open("a").write("10:30 tool=Edit target=b.md\n")
    (sessions / f".last-recap-{sid8}").unlink(missing_ok=True)
    fake2 = make_fake_claude(tmp_path / "f2", _canned_kpt_only())
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake2), state_home=state)

    text = (daily / f"{today.isoformat()}.md").read_text()
    assert text.count(f"<!-- kg-recap-sid:{sid8} -->") == 1   # ONE block
    assert "- 09:00  Edit a.md" in text and "- 10:30  Edit b.md" in text  # timeline grew
    assert (sessions / f"{sid8}.cursor").read_text().strip() == "10:30"
```

Add a new gate test:

```python
def test_nonsubstantive_stop_appends_timeline_without_calling_claude(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "readonly1"
    # 2 read-only calls, below the default 5-call / 5-min floor.
    write_session_log(state, sid8,
                      ["09:00 tool=mcp__Notion__notion-fetch target=x",
                       "09:00 tool=WebSearch target=y"])
    # Fake claude that, if called, would write a sentinel we can detect.
    fake = make_fake_claude(tmp_path, "### KPT\n- Keep: SHOULD_NOT_APPEAR\n- Problem: -\n- Try: -\n")
    env = happy_env(vault, fake)
    res = run_hook({"session_id": sid8 + "-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    note = daily / f"{_dt.date.today().isoformat()}.md"
    assert note.exists()
    content = note.read_text()
    assert "### Timeline" in content
    assert "SHOULD_NOT_APPEAR" not in content   # LLM never ran
    assert "### KPT" not in content
```

Keep `test_idempotent_replaces_existing_block` semantics by reframing: after two substantive runs over the same window (cursor cleared), the KPT is replaced and Timeline not duplicated. Update its assertions to the bare marker and `### KPT` body. Keep `test_rerun_same_window_is_idempotent` but assert the bare marker appears exactly twice (open+close) and the single Timeline bullet appears once.

For `test_legacy_bare_sid_block_left_untouched`: the legacy seed used a *different* sid (`oldlegcy`); that still holds. Also add a legacy block keyed `f"{sid8}-1400"` (HHMM form) for the **same** sid and assert the new bare-`sid8` block is created beside it (covers the `(?![-\w])` guard end-to-end).

**Commit-subject tests changed semantics.** `topic` is no longer parsed from the block heading — Task 7 derives it from the KPT's `Keep:` bullet (`_topic_from_kpt`, first 30 chars). Update `test_commit_subject_includes_topic_from_block_heading`: with the canned KPT `- Keep: テストが書ける`, assert the subject is `f"water: {today} {start} 〜 テストが書ける"` where `start` is the window start (`09:00`). For `test_commit_subject_falls_back_when_heading_missing`: feed a canned KPT whose `Keep:` line is empty (`- Keep: (なし)` → `_topic_from_kpt` returns `(なし)`, which is a topic, so the fallback no longer triggers on a missing heading). Instead, to exercise the marker-key fallback, make the LLM emit **no** `### KPT` section at all (so `topic == ""` and `note.commit(..., None)`), and assert `f"water: {today} daily auto-recap ({sid8})"` — note the marker key is now the bare `sid8`, not `sid8-HHMM`.

- [ ] **Step 4: Sweep remaining marker-format assertions**

Search the test file for `-0900`, `-1030`, `-1100`, `-1400`, `-2100`, `marker_key=` and the `heading_hhmm=` params; update each to the bare-`sid8` model or delete the now-irrelevant parameter. Run:

Run: `PYTHONPATH=. python -m pytest tests/test_auto_recap.py -v`
Expected: PASS. Fix assertions until green; do not weaken a test to pass — if a behavior genuinely changed, the assertion should reflect the new (correct) behavior.

- [ ] **Step 5: Full suite**

Run: `PYTHONPATH=. python -m pytest tests/ -q`
Expected: PASS (all files).

- [ ] **Step 6: Commit**

```bash
git add tests/test_auto_recap.py
git commit -m "test(recap): migrate integration tests to coalesced two-layer block"
```

---

## Task 9: docs + version bump

**Files:**
- Modify: `CLAUDE.md` (hook description: per-session coalesce, two-layer block)
- Modify: `README.md` if it documents auto-recap block shape or `KG_RECAP_MIN_*`
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `package.json` (version)

- [ ] **Step 1: Document the new env vars + behaviour**

In `CLAUDE.md`, update the `Stop` hook bullet to describe: one block per `sid8`, append-only `### Timeline` (mechanical), `### KPT` regenerated from the transcript only on substantive Stops, and the `KG_RECAP_MIN_CALLS` / `KG_RECAP_MIN_MINUTES` gate env vars (defaults 5 / 5).

- [ ] **Step 2: Bump version 0.15.2 → 0.16.0**

Edit the `"version"` field in all three files to `0.16.0`.

Run: `PYTHONPATH=. python -m pytest tests/ -q && pre-commit run --files .claude-plugin/plugin.json .claude-plugin/marketplace.json package.json CLAUDE.md`
Expected: tests PASS; the "versions match" pre-commit hook PASSES (all three agree on 0.16.0).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md .claude-plugin/plugin.json .claude-plugin/marketplace.json package.json
git commit -m "chore(release): recap session coalesce (v0.16.0)"
```

---

## Final verification

- [ ] **Run the whole suite + pre-commit on all touched files**

Run: `PYTHONPATH=. python -m pytest tests/ -v`
Expected: all green.

Run: `pre-commit run --all-files`
Expected: pass (or only unrelated pre-existing warnings).

- [ ] **Manual smoke (optional, real vault):** With `KG_AUTO_RECAP=1` and a throwaway `KG_VAULT`, drive two Stop events in one session and confirm the daily note has a single `kg-recap-sid:<sid8>` block whose Timeline grew across both Stops and whose KPT was rewritten once.
