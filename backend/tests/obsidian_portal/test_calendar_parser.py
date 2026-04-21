"""Tests for obsidian_portal/calendar_parser.py."""

import pytest

from lorekeeper.obsidian_portal.calendar_parser import (
    CalendarDate,
    CalendarPage,
    MonthBlock,
    _date_to_ordinal,
    _insert_link_in_month,
    _insert_link_in_special_day,
    _new_month_accordion_item,
    add_entry,
    get_entries,
    is_leap_year,
    parse_body,
    render_body,
)

# ── Fixtures / helpers ─────────────────────────────────────────────────────────

_HAMMER_ITEM = (
    "[accordion-item] [title]Hammer[end-title] [content]\n"
    '<table id="calendar" align="center" border="1" cellpadding="2" cellspacing="5"\n'
    '       style="width:1000px; table-layout: fixed">\n'
    "    <tbody>\n"
    "    <tr>\n"
    '        <td class="date">\n'
    '            <div class="date-cell">\n'
    '                <div class="date-content">\n'
    "                    [[Battle of Bones | Battle of Bones]]\n"
    "                </div>\n"
    '                <div class="date-number">\n'
    "                    1\n"
    "                </div>\n"
    "            </div>\n"
    "        </td>\n"
    '        <td class="date">\n'
    '            <div class="date-cell">\n'
    '                <div class="date-content">\n'
    "                </div>\n"
    '                <div class="date-number">\n'
    "                    2\n"
    "                </div>\n"
    "            </div>\n"
    "        </td>\n"
    "    </tr>\n"
    "    </tbody>\n"
    "</table>\n"
    "[end-content] [end-accordion-item]\n"
)

_MIDWINTER_ITEM = (
    "[accordion-item] [title]Midwinter[end-title] [content]\n"
    "[[Midwinter Festival | Midwinter Festival]]\n"
    "[end-content] [end-accordion-item]\n"
)

_SHIELDMEET_ITEM = "[accordion-item] [title]Shieldmeet[end-title] [content]\n[end-content] [end-accordion-item]\n"


def _make_minimal_body(year: int = 1372, include_shieldmeet: bool = False) -> str:
    sections = _MIDWINTER_ITEM + _HAMMER_ITEM
    if include_shieldmeet:
        sections += _SHIELDMEET_ITEM
    return "Some intro text.\n" + f"h2. {year}\n" + "[accordion] \n" + sections + "[end-accordion]\n\n\n\n"


def _make_body_with_hidden_div(year: int = 1372) -> str:
    hidden = (
        '<div style="visibility: hidden;">\n'
        "[accordion-item] [title]Example[end-title] [content]\nstuff\n[end-content] [end-accordion-item]\n"
        "</div>\n"
    )
    return _make_minimal_body(year) + hidden


def _build_page_with_entries() -> CalendarPage:
    """Two-year page with known entries for query tests (years stored newest-first)."""
    return parse_body(_make_minimal_body(1373) + _make_minimal_body(1372))


# ── parse_body / render_body round-trip ───────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(_make_minimal_body(), id="basic"),
        pytest.param(_make_body_with_hidden_div(), id="with-hidden-div"),
        pytest.param(_make_minimal_body(1373) + _make_minimal_body(1372), id="multi-year"),
        pytest.param(_make_minimal_body(1372, include_shieldmeet=True), id="with-shieldmeet"),
    ],
)
def test_parse_render_roundtrip(raw: str) -> None:
    assert render_body(parse_body(raw)) == raw


def test_parse_body_pre_content() -> None:
    page = parse_body(_make_minimal_body())
    assert page.pre == "Some intro text.\n"


def test_parse_body_year_values() -> None:
    page = parse_body(_make_minimal_body(1373) + _make_minimal_body(1372))
    years = {y.year for y in page.years}
    assert years == {1372, 1373}


def test_parse_body_sections_include_hammer_and_midwinter() -> None:
    page = parse_body(_make_minimal_body())
    section_names = {s.month if isinstance(s, MonthBlock) else s.name for s in page.years[0].sections}
    assert {"Hammer", "Midwinter"} <= section_names


def test_parse_body_hidden_div_captured() -> None:
    page = parse_body(_make_body_with_hidden_div())
    assert '<div style="visibility: hidden;">' in page.hidden_div


def test_parse_body_no_hidden_div() -> None:
    page = parse_body(_make_minimal_body())
    assert page.hidden_div == ""


def test_render_body_empty_page() -> None:
    assert render_body(CalendarPage(pre="intro\n")) == "intro\n"


# ── is_leap_year ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "year,expected",
    [
        pytest.param(0, True, id="year-0"),
        pytest.param(4, True, id="year-4"),
        pytest.param(1372, True, id="year-1372"),
        pytest.param(1376, True, id="year-1376"),
        pytest.param(1, False, id="year-1"),
        pytest.param(3, False, id="year-3"),
        pytest.param(1373, False, id="year-1373"),
        pytest.param(1374, False, id="year-1374"),
        pytest.param(1375, False, id="year-1375"),
    ],
)
def test_is_leap_year(year: int, expected: bool) -> None:
    assert is_leap_year(year) is expected


# ── _date_to_ordinal ──────────────────────────────────────────────────────────


def test_ordinal_year_ordering() -> None:
    d1 = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    d2 = CalendarDate(year=1373, month_or_special_day="Hammer", day=1)
    assert _date_to_ordinal(d1) < _date_to_ordinal(d2)


def test_ordinal_month_ordering_within_year() -> None:
    hammer = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    alturiak = CalendarDate(year=1372, month_or_special_day="Alturiak", day=1)
    assert _date_to_ordinal(hammer) < _date_to_ordinal(alturiak)


def test_ordinal_day_ordering_within_month() -> None:
    d1 = CalendarDate(year=1372, month_or_special_day="Ches", day=5)
    d2 = CalendarDate(year=1372, month_or_special_day="Ches", day=15)
    assert _date_to_ordinal(d1) < _date_to_ordinal(d2)


def test_ordinal_special_day_uses_zero_day() -> None:
    assert _date_to_ordinal(CalendarDate(year=1372, month_or_special_day="Midwinter"))[2] == 0


@pytest.mark.parametrize(
    "before,special_day,after",
    [
        pytest.param(
            CalendarDate(year=1372, month_or_special_day="Hammer", day=30),
            CalendarDate(year=1372, month_or_special_day="Midwinter"),
            CalendarDate(year=1372, month_or_special_day="Alturiak", day=1),
            id="midwinter-between-hammer-alturiak",
        ),
        pytest.param(
            CalendarDate(year=1372, month_or_special_day="Tarsakh", day=30),
            CalendarDate(year=1372, month_or_special_day="Greengrass"),
            CalendarDate(year=1372, month_or_special_day="Mirtul", day=1),
            id="greengrass-between-tarsakh-mirtul",
        ),
        pytest.param(
            CalendarDate(year=1372, month_or_special_day="Flamerule", day=30),
            CalendarDate(year=1372, month_or_special_day="Midsummer"),
            CalendarDate(year=1372, month_or_special_day="Eleasis", day=1),
            id="midsummer-between-flamerule-eleasis",
        ),
    ],
)
def test_ordinal_special_day_between_months(
    before: CalendarDate,
    special_day: CalendarDate,
    after: CalendarDate,
) -> None:
    assert _date_to_ordinal(before) < _date_to_ordinal(special_day)
    assert _date_to_ordinal(special_day) < _date_to_ordinal(after)


def test_ordinal_midsummer_before_shieldmeet() -> None:
    midsummer = CalendarDate(year=1372, month_or_special_day="Midsummer")
    shieldmeet = CalendarDate(year=1372, month_or_special_day="Shieldmeet")
    assert _date_to_ordinal(midsummer) < _date_to_ordinal(shieldmeet)


# ── get_entries ───────────────────────────────────────────────────────────────


def test_get_entries_single_date_with_link() -> None:
    page = _build_page_with_entries()
    start = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    results = get_entries(page, start)
    assert len(results) == 1
    date, links = results[0]
    assert (date.year, date.month_or_special_day, date.day) == (1372, "Hammer", 1)
    assert "Battle of Bones" in links


def test_get_entries_single_date_no_entries() -> None:
    page = _build_page_with_entries()
    assert get_entries(page, CalendarDate(year=1372, month_or_special_day="Hammer", day=2)) == []


def test_get_entries_special_day_with_link() -> None:
    page = _build_page_with_entries()
    results = get_entries(page, CalendarDate(year=1372, month_or_special_day="Midwinter"))
    assert len(results) == 1
    date, links = results[0]
    assert date.month_or_special_day == "Midwinter"
    assert "Midwinter Festival" in links


def test_get_entries_multi_year_range() -> None:
    page = _build_page_with_entries()
    start = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    end = CalendarDate(year=1373, month_or_special_day="Hammer", day=1)
    years = {d.year for d, _ in get_entries(page, start, end)}
    assert years == {1372, 1373}


def test_get_entries_chronological_order() -> None:
    page = _build_page_with_entries()
    start = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    end = CalendarDate(year=1373, month_or_special_day="Hammer", day=1)
    ordinals = [_date_to_ordinal(d) for d, _ in get_entries(page, start, end)]
    assert ordinals == sorted(ordinals)


def test_get_entries_start_equals_end_is_valid() -> None:
    page = _build_page_with_entries()
    d = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    assert len(get_entries(page, d, d)) == 1


def test_get_entries_special_day_in_range() -> None:
    page = _build_page_with_entries()
    start = CalendarDate(year=1372, month_or_special_day="Hammer", day=30)
    end = CalendarDate(year=1372, month_or_special_day="Alturiak", day=1)
    names = [d.month_or_special_day for d, _ in get_entries(page, start, end)]
    assert "Midwinter" in names


def test_get_entries_year_outside_range_skipped() -> None:
    page = _build_page_with_entries()
    start = CalendarDate(year=1373, month_or_special_day="Hammer", day=1)
    end = CalendarDate(year=1373, month_or_special_day="Hammer", day=1)
    assert all(d.year == 1373 for d, _ in get_entries(page, start, end))


def test_get_entries_start_greater_than_end_raises() -> None:
    page = _build_page_with_entries()
    start = CalendarDate(year=1373, month_or_special_day="Hammer", day=1)
    end = CalendarDate(year=1372, month_or_special_day="Hammer", day=1)
    with pytest.raises(ValueError, match="start date"):
        get_entries(page, start, end)


# ── _insert_link_in_month ─────────────────────────────────────────────────────


def test_insert_link_in_month_inserts_into_empty_cell() -> None:
    result = _insert_link_in_month(_HAMMER_ITEM, 2, "[[New Entry | New Entry]]")
    assert "[[New Entry | New Entry]]" in result


def test_insert_link_in_month_preserves_existing_content() -> None:
    result = _insert_link_in_month(_HAMMER_ITEM, 1, "[[New Entry | New Entry]]")
    assert "[[Battle of Bones | Battle of Bones]]" in result
    assert "[[New Entry | New Entry]]" in result


def test_insert_link_in_month_day_not_found_raises() -> None:
    with pytest.raises(ValueError, match="Day 99 not found"):
        _insert_link_in_month(_HAMMER_ITEM, 99, "[[X | X]]")


def test_insert_link_in_month_malformed_cell_no_closing_div() -> None:
    malformed = (
        "[accordion-item] [title]Hammer[end-title] [content]\n"
        '<table id="calendar" align="center" border="1" cellpadding="2" cellspacing="5"\n'
        '       style="width:1000px; table-layout: fixed">\n'
        "    <tbody>\n    <tr>\n"
        '        <td class="date">\n'
        '            <div class="date-cell">\n'
        '                <div class="date-content">\n'
        # Missing </div> before date-number
        '                <div class="date-number">\n                    5\n                </div>\n'
        "            </div>\n        </td>\n    </tr>\n    </tbody>\n</table>\n"
        "[end-content] [end-accordion-item]\n"
    )
    result = _insert_link_in_month(malformed, 5, "[[Test | Test]]")
    assert "[[Test | Test]]" in result


def test_insert_link_in_month_structure_intact_after_insert() -> None:
    result = _insert_link_in_month(_HAMMER_ITEM, 2, "[[Round Trip | Round Trip]]")
    assert "[title]Hammer[end-title]" in result
    assert "[end-accordion-item]" in result


# ── _insert_link_in_special_day ───────────────────────────────────────────────


def test_insert_link_in_special_day_empty_content() -> None:
    result = _insert_link_in_special_day(_SHIELDMEET_ITEM, "[[Joust | Joust]]")
    assert "[[Joust | Joust]]" in result


def test_insert_link_in_special_day_preserves_existing_content() -> None:
    result = _insert_link_in_special_day(_MIDWINTER_ITEM, "[[Second Event | Second Event]]")
    assert "[[Midwinter Festival | Midwinter Festival]]" in result
    assert "[[Second Event | Second Event]]" in result


def test_insert_link_in_special_day_structure_intact() -> None:
    result = _insert_link_in_special_day(_SHIELDMEET_ITEM, "[[X | X]]")
    assert "[content]" in result
    assert "[end-content]" in result
    assert "[end-accordion-item]" in result


def test_insert_link_in_special_day_multiple_inserts() -> None:
    r1 = _insert_link_in_special_day(_SHIELDMEET_ITEM, "[[Alpha | Alpha]]")
    r2 = _insert_link_in_special_day(r1, "[[Beta | Beta]]")
    assert "[[Alpha | Alpha]]" in r2
    assert "[[Beta | Beta]]" in r2


# ── _new_month_accordion_item ─────────────────────────────────────────────────


@pytest.mark.parametrize("month", ["Hammer", "Flamerule", "Nightal"])
def test_new_month_accordion_item_title(month: str) -> None:
    assert f"[title]{month}[end-title]" in _new_month_accordion_item(month)


def test_new_month_accordion_item_structure() -> None:
    """Structural invariants: wrapping tags, table, 3 rows, 30 cells of each kind."""
    item = _new_month_accordion_item("Ches")
    assert item.startswith("[accordion-item]")
    assert item.endswith("[end-accordion-item]\n")
    assert '<table id="calendar"' in item
    assert "<tbody>" in item
    assert item.count("<tr>") == 3
    assert item.count('<div class="date-content">') == 30
    assert item.count('<div class="date-number">') == 30


def test_new_month_accordion_item_all_30_days_present() -> None:
    item = _new_month_accordion_item("Tarsakh")
    for day in range(1, 31):
        # Use the exact indented format from the cell template so "1" doesn't false-match "10"
        assert f"                    {day}\n" in item


def test_new_month_accordion_item_roundtrip_after_insert() -> None:
    item = _new_month_accordion_item("Tarsakh")
    result = _insert_link_in_month(item, 15, "[[Event | Event]]")
    assert "[[Event | Event]]" in result


# ── add_entry ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "year,month_or_special_day,day,match",
    [
        pytest.param(1373, "Shieldmeet", None, "not a leap year", id="shieldmeet-non-leap-year"),
        pytest.param(1372, "Midwinter", 5, "does not have a day number", id="special-day-with-day-number"),
        pytest.param(1372, "Hammer", None, "day number", id="regular-month-without-day"),
    ],
)
def test_add_entry_invalid_date_raises(
    year: int,
    month_or_special_day: str,
    day: int | None,
    match: str,
) -> None:
    page = parse_body(_make_minimal_body(year))
    with pytest.raises(ValueError, match=match):
        add_entry(page, CalendarDate(year=year, month_or_special_day=month_or_special_day, day=day), "Event")


def test_add_entry_normal_month_day_insertion() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Hammer", day=2), "New Battle")
    assert "[[New Battle | New Battle]]" in render_body(page)


def test_add_entry_special_day_insertion() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Midwinter"), "Midwinter Gala")
    assert "[[Midwinter Gala | Midwinter Gala]]" in render_body(page)


def test_add_entry_shieldmeet_in_leap_year_succeeds() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Shieldmeet"), "Grand Council")
    assert "[[Grand Council | Grand Council]]" in render_body(page)


def test_add_entry_creates_year_if_missing() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1400, month_or_special_day="Ches", day=1), "Future Event")
    assert 1400 in {y.year for y in page.years}


def test_add_entry_creates_month_section_if_missing() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Nightal", day=10), "Winter Solstice")
    rendered = render_body(page)
    assert "Nightal" in rendered
    assert "[[Winter Solstice | Winter Solstice]]" in rendered


def test_add_entry_creates_special_day_section_if_missing() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Highharvestide"), "Harvest Feast")
    rendered = render_body(page)
    assert "Highharvestide" in rendered
    assert "[[Harvest Feast | Harvest Feast]]" in rendered


def test_add_entry_preserves_existing_content_on_same_day() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Hammer", day=1), "Second Event")
    rendered = render_body(page)
    assert "[[Battle of Bones | Battle of Bones]]" in rendered
    assert "[[Second Event | Second Event]]" in rendered


def test_add_entry_new_year_inserted_newest_first() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1380, month_or_special_day="Ches", day=1), "Far Future")
    assert page.years[0].year == 1380


def test_add_entry_section_inserted_in_calendar_order() -> None:
    """Alturiak should be inserted between existing Hammer and Ches sections."""
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Ches", day=5), "Ches Event")
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Alturiak", day=3), "Alt Event")
    year_block = next(y for y in page.years if y.year == 1372)
    names = [s.month if isinstance(s, MonthBlock) else s.name for s in year_block.sections]
    assert names.index("Hammer") < names.index("Alturiak") < names.index("Ches")


def test_add_entry_round_trip_after_mutation() -> None:
    page = parse_body(_make_minimal_body(1372))
    add_entry(page, CalendarDate(year=1372, month_or_special_day="Hammer", day=1), "Test Entry")
    rendered = render_body(page)
    assert render_body(parse_body(rendered)) == rendered
