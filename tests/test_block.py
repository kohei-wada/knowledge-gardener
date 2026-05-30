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
    assert "- 09:00  Edit a.py" in second
    assert "- 10:30  Edit b.py" in second
    assert second.index("- 09:00") < second.index("- 10:30")
    assert "Keep: updated" in second
    assert "Keep: a" not in second
    assert second.count("### KPT") == 1
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
    assert "Keep: a" in second
    assert "- 09:10  Bash: ls" in second
    assert "## Session 09:00〜09:10  t1" in second


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
    # Second write: substantive update adds a topic + KPT.
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="10:00", topic="recap work",
        timeline_bullets=["- 10:00  Edit a.py"], kpt_section=KPT1,
    )
    assert "### Timeline" in second              # heading MUST survive
    assert "- 09:00  MCP Notion×1" in second     # prior bullet preserved
    assert "- 10:00  Edit a.py" in second        # new bullet appended
    assert second.index("### Timeline") < second.index("- 09:00  MCP Notion×1")  # bullets under heading
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
