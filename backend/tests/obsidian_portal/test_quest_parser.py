"""Tests for obsidian_portal/quest_parser.py."""

from __future__ import annotations

import pytest

from lorekeeper.obsidian_portal.models import Quest
from lorekeeper.obsidian_portal.quest_parser import (
    ParsedBody,
    PhaseBlock,
    SubSection,
    _get_or_create_phase,
    _get_or_create_sub,
    _parse_half,
    _parse_items,
    _protect_regions,
    extract_quests,
    insert_quest,
    parse_body,
    render_body,
    update_quest_data,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_HIDDEN_TEMPLATE = '<div style="visibility: hidden;">template content</div>'
_SLIDESHOW = "[slideshow]slide1[end-slideshow]"


def _make_quest(
    title: str = "Test Quest",
    content: str = "Some content",
    status: str = "open",
    phase: str = "Act I",
    quest_type: str | None = "Main Quest",
) -> Quest:
    return Quest(title=title, content=content, status=status, phase=phase, quest_type=quest_type)  # type: ignore[arg-type]


def _item_str(status: str, title: str, content: str) -> str:
    """Build a single [accordion-item]...[end-accordion-item] string."""
    return (
        "\n[accordion-item]\n"
        f'[title]<div class="{status}">{title}</div>[end-title]\n'
        f"[content]{content}[end-content]\n"
        "[end-accordion-item]\n"
    )


def _accordion_block(items: list[tuple[str, str, str]]) -> str:
    """Build an [accordion]...[end-accordion] block from (status, title, content) tuples."""
    inner = "".join(_item_str(s, t, c) for s, t, c in items)
    return f"[accordion]{inner}[end-accordion]"


def _build_body(
    active_content: str = "",
    completed_content: str = "",
    hidden: str = _HIDDEN_TEMPLATE,
    slideshow: str = "",
) -> str:
    body = active_content + "h2. Completed Quests\n" + completed_content + hidden
    return slideshow + body if slideshow else body


# ── _protect_regions ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected_hidden,expected_slideshow",
    [
        pytest.param(f"before{_HIDDEN_TEMPLATE}after", _HIDDEN_TEMPLATE, "", id="hidden-div-only"),
        pytest.param(f"before{_SLIDESHOW}after", "", _SLIDESHOW, id="slideshow-only"),
        pytest.param(f"{_SLIDESHOW}content{_HIDDEN_TEMPLATE}end", _HIDDEN_TEMPLATE, _SLIDESHOW, id="both"),
        pytest.param("just plain text", "", "", id="neither"),
        pytest.param(
            'pre<div style="visibility: hidden;">\nline1\nline2\n</div>post',
            '<div style="visibility: hidden;">\nline1\nline2\n</div>',
            "",
            id="multiline-hidden-div",
        ),
        pytest.param(
            "before\n[slideshow]\nslide A\nslide B\n[end-slideshow]\nafter",
            "",
            "[slideshow]\nslide A\nslide B\n[end-slideshow]",
            id="multiline-slideshow",
        ),
    ],
)
def test_protect_regions(raw: str, expected_hidden: str, expected_slideshow: str) -> None:
    result, hidden, slideshow = _protect_regions(raw)
    assert hidden == expected_hidden
    assert slideshow == expected_slideshow
    if expected_hidden:
        assert "\x00HIDDEN\x00" in result
        assert expected_hidden not in result
    if expected_slideshow:
        assert "\x00SLIDESHOW\x00" in result
        assert expected_slideshow not in result
    if not expected_hidden and not expected_slideshow:
        assert result == raw


# ── _parse_items ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,title,content,quest_type,phase",
    [
        pytest.param("open", "Dragon Hunt", "Find the dragon.", "Main Quest", "Act I", id="status-open"),
        pytest.param("failed", "Dead End", "Gone.", "Side Quest", "Act III", id="status-failed"),
        pytest.param("completed", "Done Deal", "Finished.", None, "Epilogue", id="status-completed-no-type"),
    ],
)
def test_parse_items_single_item(
    status: str,
    title: str,
    content: str,
    quest_type: str | None,
    phase: str,
) -> None:
    quests = _parse_items(_item_str(status, title, content), phase, quest_type)
    assert len(quests) == 1
    assert quests[0].title == title
    assert quests[0].content == content
    assert quests[0].status == status
    assert quests[0].phase == phase
    assert quests[0].quest_type == quest_type


def test_parse_items_multiple_items() -> None:
    inner = _item_str("open", "Quest A", "Content A") + _item_str("completed", "Quest B", "Content B")
    quests = _parse_items(inner, "Act II", "Side Quest")
    assert len(quests) == 2
    assert quests[0].title == "Quest A"
    assert quests[1].title == "Quest B"
    assert quests[1].status == "completed"


def test_parse_items_empty_input_returns_empty_list() -> None:
    assert _parse_items("   \n   ", "Act I", "Main Quest") == []


def test_parse_items_malformed_item_missing_end_tag_returns_empty_list() -> None:
    inner = (
        '\n[accordion-item]\n[title]<div class="open">Broken</div>[end-title]\n[content]content[end-content]\n'
        # Missing [end-accordion-item]
    )
    assert _parse_items(inner, "Act I", "Main Quest") == []


# ── _parse_half ───────────────────────────────────────────────────────────────


def test_parse_half_no_h3_returns_all_as_pre() -> None:
    text = "Just some plain text before any phases."
    pre, phases = _parse_half(text)
    assert pre == text
    assert phases == []


def test_parse_half_single_phase_with_direct_accordion() -> None:
    acc = _accordion_block([("open", "Big Quest", "Details here")])
    pre, phases = _parse_half('<h3 class="quests">Act I</h3>' + acc)
    assert pre == ""
    assert len(phases) == 1
    phase = phases[0]
    assert phase.phase_name == "Act I"
    assert len(phase.sub_sections) == 1
    assert phase.sub_sections[0].quest_type is None
    assert phase.sub_sections[0].quests[0].title == "Big Quest"


def test_parse_half_phase_with_subtypes() -> None:
    main_acc = _accordion_block([("open", "Main One", "main content")])
    side_acc = _accordion_block([("completed", "Side One", "side content")])
    text = (
        '<h3 class="quests">Act I</h3>\n'
        '<h3 class="quests">Main Quests</h3>' + main_acc + '<h3 class="quests">Side Quests</h3>' + side_acc
    )
    _, phases = _parse_half(text)
    assert len(phases) == 1
    assert phases[0].phase_name == "Act I"
    assert phases[0].sub_sections[0].quest_type == "Main Quest"
    assert phases[0].sub_sections[1].quest_type == "Side Quest"


def test_parse_half_personal_quests_stored_verbatim() -> None:
    text = '<h3 class="quests">Personal Quests</h3>verbatim data here'
    _, phases = _parse_half(text)
    assert len(phases) == 1
    assert phases[0].phase_name == "Personal Quests"
    assert phases[0].raw_personal == "verbatim data here"
    assert phases[0].sub_sections == []


def test_parse_half_orphaned_subtype_header_creates_synthetic_phase() -> None:
    acc = _accordion_block([("open", "Orphan Quest", "detail")])
    _, phases = _parse_half('<h3 class="quests">Main Quests</h3>' + acc)
    assert len(phases) == 1
    assert phases[0].phase_name == ""
    assert phases[0].sub_sections[0].quest_type == "Main Quest"


def test_parse_half_multiple_phases() -> None:
    acc1 = _accordion_block([("open", "Q1", "c1")])
    acc2 = _accordion_block([("completed", "Q2", "c2")])
    text = '<h3 class="quests">Act I</h3>' + acc1 + '<h3 class="quests">Act II</h3>' + acc2
    _, phases = _parse_half(text)
    assert len(phases) == 2
    assert [p.phase_name for p in phases] == ["Act I", "Act II"]


def test_parse_half_pre_text_preserved() -> None:
    acc = _accordion_block([("open", "Q", "c")])
    pre, phases = _parse_half("PREAMBLE\n" + '<h3 class="quests">Act I</h3>' + acc)
    assert pre == "PREAMBLE\n"
    assert len(phases) == 1


def test_parse_half_phase_header_suffix_preserved() -> None:
    acc = _accordion_block([("open", "MQ1", "stuff")])
    text = '<h3 class="quests">Act I</h3>\n(some notes)\n<h3 class="quests">Main Quests</h3>' + acc
    _, phases = _parse_half(text)
    assert phases[0].header_suffix == "\n(some notes)\n"


# ── parse_body / render_body round-trip ───────────────────────────────────────


def _rt_minimal() -> str:
    return _build_body(
        active_content='<h3 class="quests">Act I</h3>'
        + _accordion_block([("open", "Dragon Hunt", "Kill the dragon.")])
        + "\n",
    )


def _rt_with_slideshow() -> str:
    acc = _accordion_block([("open", "Epic Quest", "Big story.")])
    return _SLIDESHOW + "\n" + '<h3 class="quests">Act I</h3>' + acc + "\nh2. Completed Quests\n" + _HIDDEN_TEMPLATE


def _rt_completed_quests() -> str:
    return (
        '<h3 class="quests">Act I</h3>'
        + _accordion_block([("open", "Active One", "running")])
        + "\nh2. Completed Quests\n"
        + '<h3 class="quests">Act I</h3>'
        + _accordion_block([("completed", "Done One", "finished")])
        + "\n"
        + _HIDDEN_TEMPLATE
    )


def _rt_personal_quests() -> str:
    return '<h3 class="quests">Personal Quests</h3>\npersonal data\n' + "h2. Completed Quests\n" + _HIDDEN_TEMPLATE


def _rt_multi_phase_subtypes() -> str:
    return (
        '<h3 class="quests">Act I</h3>\n'
        '<h3 class="quests">Main Quests</h3>'
        + _accordion_block([("open", "Main One", "details")])
        + '<h3 class="quests">Side Quests</h3>'
        + _accordion_block([("open", "Side One", "details")])
        + "\nh2. Completed Quests\n"
        + '<h3 class="quests">Act I</h3>'
        + _accordion_block([("completed", "Done One", "done")])
        + "\n"
        + _HIDDEN_TEMPLATE
    )


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(_rt_minimal(), id="minimal"),
        pytest.param(_rt_with_slideshow(), id="with-slideshow"),
        pytest.param(_rt_completed_quests(), id="completed-quests"),
        pytest.param(_rt_personal_quests(), id="personal-quests"),
        pytest.param(_rt_multi_phase_subtypes(), id="multi-phase-subtypes"),
        pytest.param(
            '<h3 class="quests">Act I</h3>'
            + _accordion_block([("open", "Q", "c")])
            + "\nh2. Completed Quests\n"
            + _HIDDEN_TEMPLATE,
            id="empty-completed-section",
        ),
        pytest.param("Plain preamble text.\nh2. Completed Quests\n" + _HIDDEN_TEMPLATE, id="no-h3-sections"),
        pytest.param("h2. Completed Quests\n" + _HIDDEN_TEMPLATE + "\nsome trailing text", id="post-hidden-text"),
    ],
)
def test_round_trip(raw: str) -> None:
    assert render_body(parse_body(raw)) == raw


# ── extract_quests ────────────────────────────────────────────────────────────


def test_extract_quests_from_active_phases() -> None:
    body = _build_body(
        active_content='<h3 class="quests">Act I</h3>' + _accordion_block([("open", "Active Quest", "content")]) + "\n",
    )
    quests = extract_quests(parse_body(body))
    assert len(quests) == 1
    assert quests[0].title == "Active Quest"


def test_extract_quests_from_completed_phases() -> None:
    body = (
        "h2. Completed Quests\n"
        + '<h3 class="quests">Act I</h3>'
        + _accordion_block([("completed", "Old Quest", "done")])
        + "\n"
        + _HIDDEN_TEMPLATE
    )
    quests = extract_quests(parse_body(body))
    assert len(quests) == 1
    assert quests[0].title == "Old Quest"


def test_extract_quests_excludes_personal_quests() -> None:
    body = (
        '<h3 class="quests">Personal Quests</h3>\npersonal data\n'
        + '<h3 class="quests">Act I</h3>'
        + _accordion_block([("open", "Regular Quest", "content")])
        + "\nh2. Completed Quests\n"
        + _HIDDEN_TEMPLATE
    )
    quests = extract_quests(parse_body(body))
    assert len(quests) == 1
    assert quests[0].title == "Regular Quest"


def test_extract_quests_both_sections() -> None:
    body = (
        '<h3 class="quests">Act I</h3>'
        + _accordion_block([("open", "Active One", "a")])
        + "\nh2. Completed Quests\n"
        + '<h3 class="quests">Act I</h3>'
        + _accordion_block([("completed", "Done One", "d")])
        + "\n"
        + _HIDDEN_TEMPLATE
    )
    titles = {q.title for q in extract_quests(parse_body(body))}
    assert titles == {"Active One", "Done One"}


def test_extract_quests_empty_body_returns_empty_list() -> None:
    assert extract_quests(parse_body("h2. Completed Quests\n" + _HIDDEN_TEMPLATE)) == []


# ── insert_quest ──────────────────────────────────────────────────────────────


def _empty_parsed() -> ParsedBody:
    return parse_body("h2. Completed Quests\n" + _HIDDEN_TEMPLATE)


def test_insert_quest_duplicate_title_raises() -> None:
    acc = _accordion_block([("open", "Existing", "content")])
    parsed = parse_body('<h3 class="quests">Act I</h3>' + acc + "\nh2. Completed Quests\n" + _HIDDEN_TEMPLATE)
    with pytest.raises(ValueError, match="already exists"):
        insert_quest(parsed, _make_quest(title="Existing", phase="Act I"))


def test_insert_quest_active_quest_appears_in_active_phases() -> None:
    parsed = _empty_parsed()
    insert_quest(parsed, _make_quest(title="New Quest", status="open", phase="Act I", quest_type="Main Quest"))
    assert any(q.title == "New Quest" for q in extract_quests(parsed))


def test_insert_quest_completed_quest_goes_to_completed_phases() -> None:
    parsed = _empty_parsed()
    insert_quest(parsed, _make_quest(title="Done Quest", status="completed", phase="Act I", quest_type="Side Quest"))
    comp_quests = [q for p in parsed.completed_phases for s in p.sub_sections for q in s.quests]
    assert any(q.title == "Done Quest" for q in comp_quests)


def test_insert_quest_auto_creates_phase() -> None:
    parsed = _empty_parsed()
    insert_quest(parsed, _make_quest(title="New Quest", status="open", phase="Brand New Phase"))
    assert "Brand New Phase" in [p.phase_name for p in parsed.active_phases]


def test_insert_quest_auto_creates_subsection() -> None:
    parsed = _empty_parsed()
    insert_quest(parsed, _make_quest(title="New Quest", status="open", phase="Act I", quest_type="Side Quest"))
    found = next((q for q in extract_quests(parsed) if q.title == "New Quest"), None)
    assert found is not None
    assert found.quest_type == "Side Quest"


def test_insert_quest_no_quest_type() -> None:
    parsed = _empty_parsed()
    insert_quest(parsed, _make_quest(title="Typeless Quest", quest_type=None))
    found = next((q for q in extract_quests(parsed) if q.title == "Typeless Quest"), None)
    assert found is not None
    assert found.quest_type is None


def test_insert_quest_appears_in_rendered_body() -> None:
    parsed = _empty_parsed()
    insert_quest(parsed, _make_quest(title="Render Test", content="Check this.", status="open", phase="Act I"))
    rendered = render_body(parsed)
    assert "Render Test" in rendered
    assert "Check this." in rendered


# ── update_quest_data ─────────────────────────────────────────────────────────


def _parsed_with_quest(title: str = "My Quest", status: str = "open", content: str = "content") -> ParsedBody:
    acc = _accordion_block([(status, title, content)])
    if status == "open":
        body = '<h3 class="quests">Act I</h3>' + acc + "\nh2. Completed Quests\n" + _HIDDEN_TEMPLATE
    else:
        body = "h2. Completed Quests\n" + '<h3 class="quests">Act I</h3>' + acc + "\n" + _HIDDEN_TEMPLATE
    return parse_body(body)


def test_update_quest_not_found_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        update_quest_data(_empty_parsed(), "Nonexistent Quest")


def test_update_quest_no_changes_returns_no_changes() -> None:
    assert update_quest_data(_parsed_with_quest(), "My Quest") == "no changes"


def test_update_quest_rename_to_existing_title_raises() -> None:
    acc = _accordion_block([("open", "Quest A", "c"), ("open", "Quest B", "c")])
    parsed = parse_body('<h3 class="quests">Act I</h3>' + acc + "\nh2. Completed Quests\n" + _HIDDEN_TEMPLATE)
    with pytest.raises(ValueError, match="already exists"):
        update_quest_data(parsed, "Quest A", new_title="Quest B")


def test_update_quest_in_place_title_change() -> None:
    parsed = _parsed_with_quest("Old Title")
    summary = update_quest_data(parsed, "Old Title", new_title="New Title")
    assert "Old Title" in summary and "New Title" in summary
    titles = [q.title for q in extract_quests(parsed)]
    assert "New Title" in titles and "Old Title" not in titles


def test_update_quest_in_place_content_change() -> None:
    parsed = _parsed_with_quest("Quest X", content="old content")
    summary = update_quest_data(parsed, "Quest X", new_content="new content")
    assert "content updated" in summary
    quest = next(q for q in extract_quests(parsed) if q.title == "Quest X")
    assert quest.content == "new content"


def test_update_quest_active_to_completed_moves_quest() -> None:
    parsed = _parsed_with_quest("Moving Quest", status="open")
    summary = update_quest_data(parsed, "Moving Quest", new_status="completed")
    assert "status" in summary
    active = [q.title for p in parsed.active_phases for s in p.sub_sections for q in s.quests]
    completed = [q.title for p in parsed.completed_phases for s in p.sub_sections for q in s.quests]
    assert "Moving Quest" not in active
    assert "Moving Quest" in completed


def test_update_quest_completed_to_active_moves_quest() -> None:
    parsed = _parsed_with_quest("Done Quest", status="completed")
    update_quest_data(parsed, "Done Quest", new_status="open")
    active = [q.title for p in parsed.active_phases for s in p.sub_sections for q in s.quests]
    completed = [q.title for p in parsed.completed_phases for s in p.sub_sections for q in s.quests]
    assert "Done Quest" in active
    assert "Done Quest" not in completed


def test_update_quest_phase_change() -> None:
    parsed = _parsed_with_quest("Phase Shift")
    summary = update_quest_data(parsed, "Phase Shift", new_phase="Act II")
    assert "phase" in summary
    quest = next(q for q in extract_quests(parsed) if q.title == "Phase Shift")
    assert quest.phase == "Act II"


def test_update_quest_quest_type_change() -> None:
    parsed = _parsed_with_quest("Type Swap")
    parsed.active_phases[0].sub_sections[0].quests[0] = Quest(
        title="Type Swap",
        content="content",
        status="open",
        phase="Act I",
        quest_type="Main Quest",
    )
    summary = update_quest_data(parsed, "Type Swap", new_quest_type="Side Quest")
    assert "quest_type" in summary
    quest = next(q for q in extract_quests(parsed) if q.title == "Type Swap")
    assert quest.quest_type == "Side Quest"


def test_update_quest_simultaneous_status_and_phase_change() -> None:
    parsed = _parsed_with_quest("Journey Quest", status="open")
    summary = update_quest_data(parsed, "Journey Quest", new_status="completed", new_phase="Act II")
    assert "status" in summary
    assert "phase" in summary
    active_titles = [q.title for p in parsed.active_phases for s in p.sub_sections for q in s.quests]
    all_completed = [q for p in parsed.completed_phases for s in p.sub_sections for q in s.quests]
    assert "Journey Quest" not in active_titles
    assert any(q.title == "Journey Quest" for q in all_completed)
    quest = next(q for q in all_completed if q.title == "Journey Quest")
    assert quest.phase == "Act II"
    assert quest.status == "completed"


def test_update_quest_round_trip_after_move() -> None:
    parsed = _parsed_with_quest("Journey", content="long road")
    update_quest_data(parsed, "Journey", new_status="completed")
    rendered = render_body(parsed)
    assert "Journey" in rendered and "long road" in rendered


# ── _get_or_create_phase ──────────────────────────────────────────────────────


def test_get_or_create_phase_returns_existing() -> None:
    phases: list[PhaseBlock] = [PhaseBlock(header_html='<h3 class="quests">Act I</h3>', phase_name="Act I")]
    result = _get_or_create_phase(phases, "Act I")
    assert result is phases[0]
    assert len(phases) == 1


def test_get_or_create_phase_creates_new() -> None:
    phases: list[PhaseBlock] = []
    result = _get_or_create_phase(phases, "Act II")
    assert result.phase_name == "Act II"
    assert len(phases) == 1
    assert "Act II" in result.header_html


# ── _get_or_create_sub ────────────────────────────────────────────────────────


def test_get_or_create_sub_returns_existing() -> None:
    sub = SubSection(quest_type="Main Quest", header_html='<h3 class="quests">Main Quests</h3>')
    phase = PhaseBlock(header_html="", phase_name="Act I", sub_sections=[sub])
    assert _get_or_create_sub(phase, "Main Quest") is sub
    assert len(phase.sub_sections) == 1


def test_get_or_create_sub_creates_new_with_type() -> None:
    phase = PhaseBlock(header_html="", phase_name="Act I")
    result = _get_or_create_sub(phase, "Side Quest")
    assert result.quest_type == "Side Quest"
    assert result.header_html is not None and "Side Quests" in result.header_html
    assert len(phase.sub_sections) == 1


def test_get_or_create_sub_creates_new_without_type() -> None:
    phase = PhaseBlock(header_html="", phase_name="Act I")
    result = _get_or_create_sub(phase, None)
    assert result.quest_type is None
    assert result.header_html is None
    assert len(phase.sub_sections) == 1
