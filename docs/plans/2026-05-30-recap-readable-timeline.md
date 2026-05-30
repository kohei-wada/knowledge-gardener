# Readable Timeline (AI activity-log + mechanical fallback) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily-note `### Timeline` readable and usable as 日報 raw material, while guaranteeing the time record is never lost when the LLM fails.

**Architecture:** The Timeline slot holds exactly one representation — an AI-composed activity log when the headless LLM succeeds, otherwise a deterministic noise-filtered timeline. This mirrors the existing `build_commit_subject` "LLM value or mechanical fallback" pattern. The Timeline is regenerated whole-session and replaced on each Stop (no more append-merge), so AI and mechanical lines never mix. The deterministic filter (drop `StructuredOutput`, collapse `Web×N` and read-only-nav `×N`) lives in the shared aggregator so both the auto (Stop hook) and manual (garden-recap) writers benefit.

**Tech Stack:** Python 3 stdlib only, pytest. No new dependencies.

**Spec:** `docs/specs/2026-05-30-recap-readable-timeline-design.md`

---

## File Structure

- `recap/aggregate/__main__.py` — `_summarize_minute` filter rules + `render_timeline` empty-minute skip. (Filter lives here so both writers share it.)
- `recap/autorecap/block.py` — add `extract_timeline_bullets`; change Timeline from append-merge to wholesale replace; remove the now-dead sort helpers.
- `recap/autorecap/session_aggregator.py` — aggregate the **whole session** (`since=None`) so the regenerated Timeline covers the full session.
- `recap/autorecap/__main__.py` — always write the deterministic block; upgrade Timeline + add KPT only when the LLM succeeds (remove the early `if not out: return`).
- `recap/autorecap/prompts/auto_recap_compose_prompt.md`, `auto_recap_prompt.md` — emit `### Timeline` (activity log) + `### KPT`.
- `recap/manual_recap/__main__.py` — accept optional `--timeline-file` (assistant-authored Timeline); deterministic fallback when absent.
- `skills/garden-recap/SKILL.md` — author the activity-log Timeline alongside the KPT.
- Tests: `tests/test_recap_aggregate.py`, `tests/test_block.py`, `tests/test_auto_recap.py`, `tests/test_manual_recap.py`.

**Test command (whole suite):** `PYTHONPATH=. python3 -m pytest -q`

---

## Task 1: Deterministic filter in the aggregator

**Files:**
- Modify: `recap/aggregate/__main__.py:44-82` (`_summarize_minute`, `render_timeline`)
- Test: `tests/test_recap_aggregate.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recap_aggregate.py` (it already imports `render_timeline`):

```python
def _entries(*rows):
    # rows: (hhmm, tool, target)
    return [{"hhmm": h, "tool": t, "target": g, "status": None} for h, t, g in rows]


def test_structured_output_dropped():
    out = render_timeline(_entries(
        ("11:00", "StructuredOutput", ""),
        ("11:00", "StructuredOutput", ""),
        ("11:00", "Bash", "ls"),
    ))
    assert out == ["- 11:00  Bash: ls"]


def test_web_calls_collapsed():
    out = render_timeline(_entries(
        ("11:00", "WebSearch", "q1"),
        ("11:00", "WebFetch", "https://a"),
        ("11:00", "WebFetch", "https://b"),
    ))
    assert out == ["- 11:00  Web×3"]


def test_readonly_nav_collapsed_by_tool():
    out = render_timeline(_entries(
        ("11:00", "Read", "a.py"),
        ("11:00", "Read", "b.py"),
        ("11:00", "Grep", "foo"),
    ))
    assert out == ["- 11:00  Grep×1, Read×2"]


def test_minute_with_only_noise_is_skipped():
    out = render_timeline(_entries(
        ("11:00", "StructuredOutput", ""),
        ("11:01", "Edit", "a.py"),
    ))
    assert out == ["- 11:01  Edit a.py"]


def test_bash_agent_edit_preserved():
    out = render_timeline(_entries(
        ("11:00", "Edit", "a.py"),
        ("11:00", "Bash", "git status"),
        ("11:00", "Agent", "Explore:look around"),
    ))
    assert out == ["- 11:00  Edit a.py, Bash: git status, Agent→Explore"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `PYTHONPATH=. python3 -m pytest tests/test_recap_aggregate.py -q -k "structured_output or web_calls or readonly_nav or only_noise or bash_agent_edit"`
Expected: FAIL (current code lists web/nav/StructuredOutput per call).

- [ ] **Step 3: Rewrite `_summarize_minute` and `render_timeline`**

Replace `_summarize_minute` (lines 44-75) and `render_timeline` (lines 78-82) with:

```python
WEB_TOOLS = frozenset({"WebFetch", "WebSearch"})
NOISE_TOOLS = frozenset({"StructuredOutput"})


def _summarize_minute(entries: list[dict]) -> str:
    file_counts: OrderedDict[tuple[str, str], int] = OrderedDict()
    file_err: dict[tuple[str, str], bool] = {}
    rest: list[str] = []           # Bash / Agent — itemized, in encounter order
    web = 0                        # WebFetch + WebSearch — collapsed
    mcp: Counter[str] = Counter()
    misc: Counter[str] = Counter()  # read-only nav + unknown tools — collapsed by name
    for e in entries:
        tool, target = e["tool"], (e["target"] or "?")
        err = " [err]" if e["status"] == "err" else ""
        if tool in NOISE_TOOLS:
            continue
        if tool in FILE_TOOLS:
            key = (tool, target)
            file_counts[key] = file_counts.get(key, 0) + 1
            if e["status"] == "err":
                file_err[key] = True
        elif tool == "Bash":
            rest.append(f"Bash: {target}{err}")
        elif tool == "Agent":
            sub = target.split(":", 1)[0] if ":" in target else target
            rest.append(f"Agent→{sub}{err}")
        elif tool in WEB_TOOLS:
            web += 1
        elif tool.startswith("mcp__"):
            parts = tool.split("__", 2)
            mcp[parts[1] if len(parts) >= 2 else "mcp"] += 1
        else:
            misc[tool] += 1
    chunks = [
        f"{tool} {path}" + (f" ×{n}" if n > 1 else "") + (" [err]" if file_err.get((tool, path)) else "")
        for (tool, path), n in file_counts.items()
    ]
    chunks.extend(rest)
    if web:
        chunks.append(f"Web×{web}")
    chunks.extend(f"{tool}×{n}" for tool, n in sorted(misc.items()))
    chunks.extend(f"MCP {server}×{n}" for server, n in sorted(mcp.items()))
    return ", ".join(chunks)


def render_timeline(entries: list[dict]) -> list[str]:
    by_min: OrderedDict[str, list[dict]] = OrderedDict()
    for e in entries:
        by_min.setdefault(e["hhmm"], []).append(e)
    out: list[str] = []
    for hhmm, es in by_min.items():
        summary = _summarize_minute(es)
        if summary:
            out.append(f"- {hhmm}  {summary}")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python3 -m pytest tests/test_recap_aggregate.py -q`
Expected: PASS (all, including the pre-existing aggregate tests — `webio_count` etc. are computed separately in `aggregate_session` and are unaffected).

- [ ] **Step 5: Commit**

```bash
git add recap/aggregate/__main__.py tests/test_recap_aggregate.py
git commit -m "feat(aggregate): readable Timeline filter (drop StructuredOutput, collapse Web/nav)"
```

---

## Task 2: `extract_timeline_bullets` helper

**Files:**
- Modify: `recap/autorecap/block.py` (add near `extract_kpt_section`, line 32)
- Test: `tests/test_block.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_block.py`:

```python
from recap.autorecap.block import extract_timeline_bullets  # add to the existing import line


def test_extract_timeline_bullets_from_llm_output():
    out = (
        "### Timeline\n"
        "- 09:00–09:10 設計メモを作成\n"
        "- 09:10–09:30 実装\n"
        "\n"
        "### KPT\n"
        "- Keep: x\n"
    )
    assert extract_timeline_bullets(out) == [
        "- 09:00–09:10 設計メモを作成",
        "- 09:10–09:30 実装",
    ]


def test_extract_timeline_bullets_absent_returns_none():
    assert extract_timeline_bullets("### KPT\n- Keep: x\n") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python3 -m pytest tests/test_block.py -q -k extract_timeline`
Expected: FAIL with ImportError / not defined.

- [ ] **Step 3: Implement the helper**

In `recap/autorecap/block.py`, after the `_KPT_RE` definition (line 16) add:

```python
_TIMELINE_SECTION_RE = re.compile(
    r"^### Timeline[ \t]*\n.*?(?=\n### |\n## |\n<!-- /kg-recap-sid:|\Z)",
    re.DOTALL | re.MULTILINE,
)
```

After `extract_kpt_section` (line 36) add:

```python
def extract_timeline_bullets(text: str) -> list[str] | None:
    """Pull the bullet lines out of an LLM-emitted `### Timeline` section.
    Returns None when no Timeline section is present (LLM omitted it)."""
    m = _TIMELINE_SECTION_RE.search(text)
    if not m:
        return None
    lines = m.group(0).splitlines()[1:]  # drop the "### Timeline" header line
    return [ln for ln in lines if ln.strip()]
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python3 -m pytest tests/test_block.py -q -k extract_timeline`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/block.py tests/test_block.py
git commit -m "feat(block): extract_timeline_bullets to parse LLM ### Timeline output"
```

---

## Task 3: Timeline becomes wholesale replace (not append-merge)

**Files:**
- Modify: `recap/autorecap/block.py` (`upsert_session_block` Timeline branch; remove `_timeline_sort_key` / `_TIMELINE_TIME_RE`)
- Test: `tests/test_block.py` (rewrite the 3 append-asserting tests)

- [ ] **Step 1: Rewrite the affected tests to assert REPLACE**

In `tests/test_block.py`, replace the bodies of `test_append_timeline_preserves_prior_and_replaces_kpt` (line 20), `test_timeline_append_is_idempotent_for_same_bullets` (line 39), and `test_timeline_only_append_leaves_kpt_untouched` (line 51) with these (rename the first for clarity):

```python
def test_timeline_is_replaced_not_appended():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        topic="t1", timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="09:10",
        topic="t2", timeline_bullets=["- 09:06  Edit b.py"], kpt_section=KPT2,
    )
    assert "- 09:00  Edit a.py" not in second   # old timeline gone
    assert "- 09:06  Edit b.py" in second        # replaced with new
    assert "### KPT\n- Keep: updated" in second  # KPT still replaced


def test_replace_is_idempotent_for_same_bullets():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        topic="t", timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    again = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        topic="t", timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    assert again == first


def test_timeline_replace_leaves_kpt_untouched_when_kpt_none():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        topic="t", timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="09:10",
        topic="t", timeline_bullets=["- 09:06  Edit b.py"], kpt_section=None,
    )
    assert "- 09:06  Edit b.py" in second
    assert "- 09:00  Edit a.py" not in second
    assert "### KPT\n- Keep: a" in second  # KPT preserved when incoming kpt is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=. python3 -m pytest tests/test_block.py -q -k "replaced or replace_is_idempotent or replace_leaves"`
Expected: FAIL (current code appends + sorts, so old bullets survive).

- [ ] **Step 3: Replace the Timeline-merge logic with replace**

In `recap/autorecap/block.py`, inside `upsert_session_block`, the existing-block branch currently merges the Timeline (the block that searches `_TIMELINE_RE`, builds `existing_lines`/`fresh`/`merged`, sorts by `_timeline_sort_key`). Replace that whole merge block with a wholesale replace:

```python
        tm = _TIMELINE_RE.search(block)
        if tm:
            block = block[:tm.start(2)] + "\n".join(timeline_bullets) + block[tm.end(2):]
```

Then delete the now-unused `_timeline_sort_key` function and `_TIMELINE_TIME_RE` (block.py:20-29). Leave `_TIMELINE_RE` (still used here) and the spacing-normalization lines (the two `re.sub` calls after the KPT branch) unchanged.

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=. python3 -m pytest tests/test_block.py -q`
Expected: PASS (all of test_block.py).

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/block.py tests/test_block.py
git commit -m "feat(block): replace Timeline wholesale instead of append-merge"
```

---

## Task 4: Whole-session aggregation for the block

**Files:**
- Modify: `recap/autorecap/session_aggregator.py:57`
- Test: `tests/test_session_aggregator.py`

- [ ] **Step 1: Write the failing test**

Inspect `tests/test_session_aggregator.py` for its existing fixture style (it builds a `RecapContext` and a fake aggregator subprocess or monkeypatches `_run_aggregator_json`). Add a test asserting the aggregation ignores `ctx.since` for its window — monkeypatch `_run_aggregator_json` to capture the `since` it is called with:

```python
def test_aggregate_requests_whole_session_ignoring_cursor(monkeypatch):
    import recap.autorecap.session_aggregator as sa
    captured = {}

    def fake(sid8, since):
        captured["since"] = since
        return {"first_hhmm": "09:00", "last_hhmm": "09:30", "entry_count": 3,
                "duration_min": 30, "durable_change": True, "timeline": ["- 09:00  Edit a.py"]}

    monkeypatch.setattr(sa, "_run_aggregator_json", fake)
    ctx = _make_ctx(since="09:20")          # use the module's existing ctx helper
    agg = sa.SessionAggregator(ctx).aggregate()
    assert captured["since"] is None        # whole session, not the cursor window
    assert agg.timeline == ["- 09:00  Edit a.py"]
```

If `tests/test_session_aggregator.py` has no `_make_ctx` helper, build the `RecapContext` the same way the existing tests in that file do.

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python3 -m pytest tests/test_session_aggregator.py -q -k whole_session`
Expected: FAIL (`captured["since"] == "09:20"`).

- [ ] **Step 3: Make the change**

In `recap/autorecap/session_aggregator.py`, line 57, change:

```python
        s = _run_aggregator_json(self._ctx.sid8, since=self._ctx.since)
```
to:
```python
        s = _run_aggregator_json(self._ctx.sid8, since=None)  # whole-session: Timeline is regenerated & replaced each Stop
```

(The transcript slice in `recap/autorecap/__main__.py` still uses `ctx.since`, so KPT input stays incremental.)

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python3 -m pytest tests/test_session_aggregator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/session_aggregator.py tests/test_session_aggregator.py
git commit -m "feat(autorecap): aggregate whole session for the regenerated Timeline"
```

---

## Task 5: Prompts emit `### Timeline` activity log + `### KPT`

**Files:**
- Modify: `recap/autorecap/prompts/auto_recap_compose_prompt.md`, `recap/autorecap/prompts/auto_recap_prompt.md`

- [ ] **Step 1: Update the output contract in `auto_recap_compose_prompt.md`**

Change the "Output contract (strict)" block so the model emits BOTH sections, in this order, and nothing else:

```
### Timeline

- <HH:MM–HH:MM> <活動単位の要約、日本語、1行>
- ...

### KPT

- Keep: <bullet, Japanese, 1 sentence>
- Problem: <bullet, Japanese, 1 sentence>
- Try: <bullet, Japanese, 1 sentence — concrete next action>
```

Add a "How to write the Timeline" section:

```
## Timeline rules

1. Group the mechanical Timeline input into ACTIVITY units, not per-minute tool
   calls. One bullet per coherent activity, prefixed with its `HH:MM–HH:MM` range.
2. Say WHAT was done and WHY it mattered (e.g. "Roomba i7 のマップ取得可否を調査
   (Web検索38件・dorita980 #148 等)"), not which tools fired.
3. 5–12 bullets for a whole session. Collapse long research/edit runs into one
   bullet with a count.
4. Facts only — use the mechanical Timeline + transcript as source of truth. Do
   not invent files, commits, or actions. No invented links.
5. Japanese, matching the vault language.
```

Keep the existing `{{TIMELINE}}`, `{{TRANSCRIPT_SLICE}}`, `{{PRIOR_KPT}}` inputs. Add a note that `{{TIMELINE}}` is now the whole-session deterministic timeline and is the factual basis for BOTH the activity-log Timeline and the KPT.

- [ ] **Step 2: Mirror the change in `auto_recap_prompt.md`**

Apply the same output contract + Timeline rules to `auto_recap_prompt.md` (the cold-cache discovery variant), keeping its existing discovery-output instructions intact.

- [ ] **Step 3: Commit**

```bash
git add recap/autorecap/prompts/auto_recap_compose_prompt.md recap/autorecap/prompts/auto_recap_prompt.md
git commit -m "feat(autorecap): prompt emits activity-log Timeline + KPT"
```

(No unit test here; the parsing + fallback is covered by Task 6.)

---

## Task 6: autorecap always writes deterministic block; LLM only upgrades

**Files:**
- Modify: `recap/autorecap/__main__.py:124-169`
- Test: `tests/test_auto_recap.py`

- [ ] **Step 1: Update the canned-output helper and rewrite the affected tests**

In `tests/test_auto_recap.py`, the `make_canned_output`/`KPT_BODY` helper (around line 162) currently emits only a `### KPT`. Make the canned output include a Timeline too:

```python
TIMELINE_BODY = "### Timeline\n\n- 11:00–11:05 a/b.py を編集\n"
KPT_BODY = "### KPT\n\n- Keep: テストが書ける\n- Problem: (なし)\n- Try: 次回も green\n"
# in make_canned_output / make_fake_claude: emit TIMELINE_BODY + "\n" + KPT_BODY
# (plus the kg-discovery block where the existing helper already adds it)
```

Add/rewrite these tests:

```python
def test_llm_success_uses_ai_timeline(tmp_path):
    # canned output has "### Timeline\n- 11:00–11:05 a/b.py を編集"
    # ... drive a substantive session with pre-resolved path ...
    # assert the AI timeline line is present, NOT a raw "- 11:00  Edit" mechanical line
    ...
    assert "11:00–11:05 a/b.py を編集" in content
    assert "### KPT" in content


def test_llm_failure_writes_deterministic_timeline(tmp_path):
    # fake claude exits non-zero; path pre-resolved via KG_DAILY_TEMPLATE/env
    # ... drive a substantive session ...
    assert "### Timeline" in content        # deterministic timeline still written
    assert "### KPT" not in content         # no KPT on failure
    # commit subject falls back to "daily auto-recap (<sid>)" (mechanical topic)
```

Update `test_two_stops_coalesce_into_one_block` (line 572) and `test_topicless_then_substantive_keeps_timeline` (line 594): with replace semantics the SECOND stop's Timeline replaces the first's. Assert the block still exists once and carries the latest whole-session Timeline (these stops share one whole-session aggregate in the test fake, so assert the latest content, not accumulation).

Also confirm `test_no_op_when_claude_nonzero_exit` (line 440) and `test_no_op_when_claude_binary_missing` (line 456): these currently assert NOTHING is written on LLM failure. Under the new behavior, when a path is **pre-resolved** the deterministic block IS written. Adjust them so the no-path (cold-cache) case still no-ops, and add the pre-resolved case to `test_llm_failure_writes_deterministic_timeline`. Keep the cold-cache no-op assertion (no `KG_DAILY_TEMPLATE`, no discovery → still nothing written).

- [ ] **Step 2: Run to verify the new/edited tests fail**

Run: `PYTHONPATH=. python3 -m pytest tests/test_auto_recap.py -q -k "ai_timeline or deterministic_timeline"`
Expected: FAIL.

- [ ] **Step 3: Restructure the `run()` body**

In `recap/autorecap/__main__.py`, replace the block from `kpt_section: str | None = None` (line 124) through the `note = DailyNote(...)` setup (line 165) with:

```python
        det_bullets = agg.timeline          # whole-session, deterministic, filtered
        timeline_bullets = det_bullets
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
            if out:
                if pre is None:
                    resolved = resolver.resolve_from_discovery(out)
                    if resolved is None:
                        return
                    daily_path, insert_before = resolved
                ai_bullets = extract_timeline_bullets(out)
                if ai_bullets:
                    timeline_bullets = ai_bullets
                kpt_section = extract_kpt_section(out)
                if kpt_section is None:
                    log("claude output missing ### KPT section; writing Timeline only")
                else:
                    topic = topic_from_kpt(kpt_section)
            elif pre is None:
                log("claude failed and no pre-resolved daily path -> skip")
                return
            # else: claude failed but path is known -> fall through, write deterministic block

        note = DailyNote(ctx.vault, daily_path)
```

Add `extract_timeline_bullets` to the import from `.block` (line 29):
```python
from .block import extract_kpt_section, topic_from_kpt, extract_timeline_bullets
```

Leave the `apply_block(...)` call and everything after it unchanged — it already passes `timeline_bullets=timeline_bullets, kpt_section=kpt_section`.

- [ ] **Step 4: Run the autorecap suite**

Run: `PYTHONPATH=. python3 -m pytest tests/test_auto_recap.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recap/autorecap/__main__.py tests/test_auto_recap.py
git commit -m "feat(autorecap): always write deterministic Timeline; LLM only upgrades it + adds KPT"
```

---

## Task 7: Manual recap accepts an authored Timeline

**Files:**
- Modify: `recap/manual_recap/__main__.py`
- Modify: `skills/garden-recap/SKILL.md`
- Test: `tests/test_manual_recap.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_manual_recap.py` (follow its existing fixture for writing a session log + invoking `main`), add:

```python
def test_authored_timeline_file_overrides_mechanical(tmp_path, ...):
    # write a session log with raw tool calls
    # write a --timeline-file containing:
    #   "### Timeline\n- 09:00–09:10 設計\n"
    # invoke main([... "--timeline-file", str(tlfile), "--kpt-file", str(kptfile), "--no-commit"])
    content = daily_path.read_text(encoding="utf-8")
    assert "- 09:00–09:10 設計" in content      # authored timeline used
    assert "tool=" not in content                # raw log not leaked


def test_no_timeline_file_falls_back_to_deterministic(tmp_path, ...):
    # invoke main without --timeline-file
    content = daily_path.read_text(encoding="utf-8")
    assert "### Timeline" in content             # deterministic filtered timeline written
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python3 -m pytest tests/test_manual_recap.py -q -k "authored_timeline or falls_back_to_deterministic"`
Expected: FAIL (no `--timeline-file` arg yet).

- [ ] **Step 3: Add `--timeline-file` and use it**

In `recap/manual_recap/__main__.py`:

Add the argument in `parse_args` (after `--kpt-file`, line 30):
```python
    p.add_argument("--timeline-file", default="", help="File containing the assistant-authored ### Timeline section. When omitted, the deterministic filtered timeline is used.")
```

Reuse the `extract_timeline_bullets` helper. Add to the import (line 19):
```python
from ..autorecap.block import topic_from_kpt, upsert_session_block, extract_timeline_bullets
```

After `timeline = agg["timeline"]` (line 64) add:
```python
    if args.timeline_file:
        try:
            authored = pathlib.Path(args.timeline_file).read_text(encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"cannot read --timeline-file: {e}\n")
            return 2
        bullets = extract_timeline_bullets(authored)
        if bullets:
            timeline = bullets
```

(The rest — `upsert_session_block(..., timeline_bullets=timeline, ...)` and `apply_block(..., timeline_bullets=timeline, ...)` — already use the `timeline` variable, so no further change.)

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python3 -m pytest tests/test_manual_recap.py -q`
Expected: PASS.

- [ ] **Step 5: Update the garden-recap skill**

In `skills/garden-recap/SKILL.md`, Step 3 (Author the KPT): instruct the assistant to ALSO author a `### Timeline` activity log (same activity-unit rules as the auto prompt — group by activity, `HH:MM–HH:MM` ranges, facts only, Japanese), write it to a temp file, and pass `--timeline-file "$TIMELINE_FILE"` to `recap.manual_recap` in Steps 4 (dry-run) and 5 (apply). Note that omitting it falls back to the deterministic filtered timeline.

- [ ] **Step 6: Commit**

```bash
git add recap/manual_recap/__main__.py tests/test_manual_recap.py skills/garden-recap/SKILL.md
git commit -m "feat(manual-recap): accept assistant-authored Timeline; deterministic fallback"
```

---

## Task 8: Full suite + docs

**Files:**
- Modify: `CLAUDE.md` (the `Stop` hook bullet describing the two-layer block)

- [ ] **Step 1: Run the whole suite + pre-commit**

Run: `PYTHONPATH=. python3 -m pytest -q && pre-commit run --all-files`
Expected: PASS (fix any lint).

- [ ] **Step 2: Update CLAUDE.md**

Update the `Stop` hook bullet (and the `v0.17.0` manual-recap note) in `CLAUDE.md` to describe the new behavior: the `### Timeline` is an AI activity log on a successful LLM call and a deterministic filtered timeline on failure (and on non-substantive Stops / manual without `--timeline-file`); it is regenerated whole-session and replaced each Stop, not append-merged; the LLM never gates whether the block is written when a daily path is resolved.

- [ ] **Step 3: Commit + open PR**

```bash
git add CLAUDE.md
git commit -m "docs: describe readable Timeline + mechanical fallback in CLAUDE.md"
git push -u origin feat/recap-readable-timeline
gh pr create --fill
```

---

## Notes / trade-offs locked in during design

- **Gate × whole-session:** aggregating whole-session means more Stops trip the
  substantive gate (entry_count grows monotonically), so the LLM regenerates more
  often. The 60s debounce (`DEBOUNCE_SECONDS`) bounds this — acceptable.
- **Cold cache + LLM failure:** when no daily path is pre-resolved (first
  substantive Stop, cache cold) AND the LLM fails, the path is unknown, so the
  block is skipped (logged). The cache warms after the first success, so the
  window is narrow. This is the one case where the deterministic block can't be
  written — documented, not a regression (the old code skipped here too).
- **Late-Stop failure reverts prose:** if a later Stop is the first to fail, the
  Timeline reverts from AI prose to the deterministic filtered form. The record
  stays complete; only the prose polish is lost. Intended.
