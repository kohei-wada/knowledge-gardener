from recap.autorecap.block import upsert_session_block, extract_kpt_section, topic_from_kpt, extract_timeline_bullets

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
    assert "kg-recap-sid:abc12345-0900" in out
    assert out.count("<!-- kg-recap-sid:abc12345 -->") == 1


def test_upsert_is_byte_idempotent_on_identical_reapply():
    kwargs = dict(start_hhmm="09:00", end_hhmm="09:05", topic="t",
                  timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1)
    once = upsert_session_block("", "abc12345", **kwargs)
    twice = upsert_session_block(once, "abc12345", **kwargs)
    thrice = upsert_session_block(twice, "abc12345", **kwargs)
    assert once == twice == thrice  # fixed point — re-applying identical inputs changes nothing


def test_update_topicless_block_keeps_timeline_heading():
    # First write: NO topic (the common non-substantive first-Stop case), no KPT.
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:30", topic="",
        timeline_bullets=["- 09:00  MCP Notion×1"], kpt_section=None,
    )
    assert "## Session 09:00〜09:30" in first
    assert "### Timeline" in first
    # Second write: substantive update replaces timeline + adds topic + KPT.
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="10:00", topic="recap work",
        timeline_bullets=["- 10:00  Edit a.py"], kpt_section=KPT1,
    )
    assert "### Timeline" in second              # heading MUST survive
    assert "- 09:00  MCP Notion×1" not in second  # old bullet replaced
    assert "- 10:00  Edit a.py" in second          # new bullets in place
    assert second.index("### Timeline") < second.index("- 10:00  Edit a.py")  # bullets under heading
    assert "## Session 09:00〜10:00  recap work" in second
    assert "### KPT" in second


def test_extract_kpt_section():
    llm = "### KPT\n- Keep: x\n- Problem: y\n- Try: z\n"
    assert extract_kpt_section(llm).startswith("### KPT")
    assert extract_kpt_section("no kpt here") is None


def test_extract_kpt_section_stops_at_next_heading():
    llm = "### KPT\n- Keep: x\n## Next\nother"
    sec = extract_kpt_section(llm)
    assert "Keep: x" in sec
    assert "## Next" not in sec


def test_topic_from_kpt_uses_first_keep_bullet():
    kpt = "### KPT\n- Keep: webdav relay を deploy した\n- Problem: x\n- Try: y"
    assert topic_from_kpt(kpt) == "webdav relay を deploy した"


def test_topic_from_kpt_truncates_to_30_chars():
    long = "あ" * 50
    assert topic_from_kpt(f"### KPT\n- Keep: {long}") == "あ" * 30


def test_topic_from_kpt_empty_when_no_keep():
    assert topic_from_kpt("### KPT\n- Problem: only") == ""


def test_timeline_replace_preserves_caller_order():
    # Caller is responsible for supplying bullets in order; replace writes them as-is.
    first = upsert_session_block(
        "", "abc12345", start_hhmm="14:41", end_hhmm="14:47", topic="t",
        timeline_bullets=["- 14:41  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="12:20", end_hhmm="14:47", topic="t",
        timeline_bullets=["- 12:20  Bash: x", "- 14:41  Edit a.py"], kpt_section=KPT1,
    )
    # Caller supplied them chronologically; output must reflect that order.
    assert second.index("- 12:20") < second.index("- 14:41")
    # Old timeline is replaced by the incoming list.
    assert second.count("- 14:41  Edit a.py") == 1


def test_update_adopts_earlier_start_in_header():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="14:41", end_hhmm="14:47", topic="t",
        timeline_bullets=["- 14:41  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="12:20", end_hhmm="15:33", topic="t",
        timeline_bullets=["- 12:20  Bash: x"], kpt_section=KPT1,
    )
    assert "## Session 12:20〜15:33  t" in second


def test_update_keeps_existing_start_when_new_is_later():
    # Auto incremental: a later slice must NOT push the start forward.
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05", topic="t",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="10:00", end_hhmm="10:05", topic="t",
        timeline_bullets=["- 10:00  Edit b.py"], kpt_section=KPT1,
    )
    assert "## Session 09:00〜10:05  t" in second


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


def test_extract_timeline_bullets_empty_section_with_blank_line():
    assert extract_timeline_bullets("### Timeline\n\n### KPT\n- Keep: x") == []


def test_extract_timeline_bullets_empty_section_no_blank_line():
    # malformed LLM output: empty Timeline directly followed by KPT, no blank line.
    # Must NOT leak KPT lines into the timeline.
    assert extract_timeline_bullets("### Timeline\n### KPT\n- Keep: x") == []


def test_timeline_replace_discards_old_bullets():
    # Under replace semantics, old bullets (including hand-edited ones) are gone
    # after a new upsert — only the incoming timeline_bullets survive.
    block = (
        "<!-- kg-recap-sid:abc12345 -->\n## Session 09:00〜09:05  t\n\n"
        "### Timeline\n- 09:05  Edit b.py\n- garbage no timestamp\n\n"
        "### KPT\n- Keep: x\n<!-- /kg-recap-sid:abc12345 -->\n"
    )
    out = upsert_session_block(
        block, "abc12345", start_hhmm="09:00", end_hhmm="09:10", topic="t",
        timeline_bullets=["- 09:00  Edit a.py"], kpt_section=KPT1,
    )
    assert "- 09:00  Edit a.py" in out
    assert "- 09:05  Edit b.py" not in out
    assert "- garbage no timestamp" not in out
