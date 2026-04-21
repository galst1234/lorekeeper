"""
Parse and render the Obsidian Portal Calendar wiki page.

The page body uses h2 year headings, accordion markup for months/special-days,
and HTML tables for day cells. This module handles:
- Parsing the body into structured objects
- Serialising back to the original markup format (round-trip invariant)
- Querying entries by date range
- Inserting new wiki-link entries on a specific date

Round-trip invariant: render_body(parse_body(raw)) == raw
(verify against the live page before deployment)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

# ── Calendar constants ─────────────────────────────────────────────────────────

MONTHS: list[str] = [
    "Hammer",
    "Alturiak",
    "Ches",
    "Tarsakh",
    "Mirtul",
    "Kythorn",
    "Flamerule",
    "Eleasis",
    "Eleint",
    "Marpenoth",
    "Uktar",
    "Nightal",
]

SPECIAL_DAYS: list[str] = [
    "Midwinter",
    "Greengrass",
    "Midsummer",
    "Shieldmeet",
    "Highharvestide",
    "Feast of the Moon",
]

# Full calendar order including special days in their correct positions
CALENDAR_ORDER: list[str] = [
    "Hammer",
    "Midwinter",
    "Alturiak",
    "Ches",
    "Tarsakh",
    "Greengrass",
    "Mirtul",
    "Kythorn",
    "Flamerule",
    "Midsummer",
    "Shieldmeet",
    "Eleasis",
    "Eleint",
    "Highharvestide",
    "Marpenoth",
    "Uktar",
    "Feast of the Moon",
    "Nightal",
]

_MONTHS_SET: frozenset[str] = frozenset(MONTHS)
_SPECIAL_DAYS_SET: frozenset[str] = frozenset(SPECIAL_DAYS)
_CALENDAR_ORDER_IDX: dict[str, int] = {name: i for i, name in enumerate(CALENDAR_ORDER)}

# ── Data model ─────────────────────────────────────────────────────────────────


class CalendarDate(BaseModel):
    """A date in the Forgotten Realms Calendar of Harptos."""

    year: int
    month_or_special_day: str  # month name OR special day name
    day: int | None = None  # None for special days (Midwinter, Greengrass, etc.)


@dataclass
class MonthBlock:
    """One month's accordion-item, including the full 30-day table."""

    month: str
    raw_accordion_item: str  # verbatim [accordion-item]...[end-accordion-item]\n; mutated in-place on add


@dataclass
class SpecialDayBlock:
    """One special day's accordion-item (no table, freeform content)."""

    name: str
    raw_accordion_item: str  # verbatim [accordion-item]...[end-accordion-item]\n; mutated in-place on add


@dataclass
class YearBlock:
    """One year's accordion section."""

    year: int
    raw_pre_sections: str  # text from h2. YEAR through [accordion]\n
    sections: list[MonthBlock | SpecialDayBlock] = field(default_factory=list)
    raw_post_sections: str = ""  # text after last [end-accordion-item] (includes [end-accordion] and trailing)


@dataclass
class CalendarPage:
    """The full parsed calendar page."""

    pre: str  # content before the first h2
    years: list[YearBlock] = field(default_factory=list)  # most recent year first
    hidden_div: str = ""  # <div style="visibility: hidden;">...</div> at end of page


# ── Compiled patterns ──────────────────────────────────────────────────────────

_YEAR_SPLIT_RE = re.compile(r"(?=h2\. \d{4})")
_ACCORDION_ITEM_RE = re.compile(r"\[accordion-item\].*?\[end-accordion-item\]\n?", re.DOTALL)
_TITLE_RE = re.compile(r"\[title\](.*?)\[end-title\]", re.DOTALL)
_WIKI_LINK_RE = re.compile(r"\[\[([^\|\]]+?)(?:\s*\|[^\]]+)?\]\]")
_CONTENT_BLOCK_RE = re.compile(r"(\[content\])(.*?)(\[end-content\])", re.DOTALL)

# Matches date-content div content and the following date-number div
_DATE_CELL_RE = re.compile(
    r'<div class="date-content">(.*?)(?:</div>\s*)?<div class="date-number">\s*(\d+)\s*</div>',
    re.DOTALL,
)

_HIDDEN_DIV_MARKER = '<div style="visibility: hidden;">'


# ── Parse ──────────────────────────────────────────────────────────────────────


def parse_body(raw: str) -> CalendarPage:
    """Parse the calendar wiki page body into a structured CalendarPage."""
    # Split off the hidden div template at the end (contains example accordion items)
    hidden_idx = raw.find(_HIDDEN_DIV_MARKER)
    if hidden_idx != -1:
        main_raw = raw[:hidden_idx]
        hidden_div = raw[hidden_idx:]
    else:
        main_raw = raw
        hidden_div = ""

    parts = _YEAR_SPLIT_RE.split(main_raw)
    pre = parts[0]
    year_texts = [p for p in parts[1:] if p]

    return CalendarPage(
        pre=pre,
        years=[_parse_year(yt) for yt in year_texts],
        hidden_div=hidden_div,
    )


def _parse_year(year_text: str) -> YearBlock:
    """Parse a single year's text block into a YearBlock."""
    year_match = re.match(r"h2\. (\d{4})", year_text)
    if not year_match:
        raise ValueError(f"Could not parse year from: {year_text[:50]!r}")
    year = int(year_match.group(1))

    all_items = list(_ACCORDION_ITEM_RE.finditer(year_text))
    if not all_items:
        return YearBlock(year=year, raw_pre_sections=year_text, sections=[], raw_post_sections="")

    raw_pre_sections = year_text[: all_items[0].start()]
    raw_post_sections = year_text[all_items[-1].end() :]

    sections: list[MonthBlock | SpecialDayBlock] = []
    for item_match in all_items:
        raw = item_match.group(0)
        title_match = _TITLE_RE.search(raw)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        if title in _MONTHS_SET:
            sections.append(MonthBlock(month=title, raw_accordion_item=raw))
        elif title in _SPECIAL_DAYS_SET:
            sections.append(SpecialDayBlock(name=title, raw_accordion_item=raw))
        # Unknown titles (e.g. hidden template items) are ignored; their spans
        # still correctly bound raw_pre_sections and raw_post_sections.

    return YearBlock(
        year=year,
        raw_pre_sections=raw_pre_sections,
        sections=sections,
        raw_post_sections=raw_post_sections,
    )


# ── Render ─────────────────────────────────────────────────────────────────────


def render_body(page: CalendarPage) -> str:
    """Serialise a CalendarPage back to the wiki page body string."""
    parts: list[str] = [page.pre]
    for year in page.years:
        parts.append(year.raw_pre_sections)
        for section in year.sections:
            parts.append(section.raw_accordion_item)
        parts.append(year.raw_post_sections)
    parts.append(page.hidden_div)
    return "".join(parts)


# ── Query helpers ──────────────────────────────────────────────────────────────


def _calendar_order_key(name: str) -> int:
    """Return the calendar-order index for a month or special day name."""
    return _CALENDAR_ORDER_IDX.get(name, 999)


def _date_to_ordinal(date: CalendarDate) -> tuple[int, int, int]:
    """Return a tuple suitable for chronological comparison."""
    return (date.year, _calendar_order_key(date.month_or_special_day), date.day or 0)


def _extract_wiki_links(text: str) -> list[str]:
    """Extract wiki-link target titles from text."""
    return [m.group(1).strip() for m in _WIKI_LINK_RE.finditer(text)]


def _get_month_day_entries(block: MonthBlock) -> list[tuple[int, list[str]]]:
    """Return (day_number, [wiki_link_titles]) for every cell in a month."""
    result: list[tuple[int, list[str]]] = []
    for m in _DATE_CELL_RE.finditer(block.raw_accordion_item):
        day_num = int(m.group(2))
        links = _extract_wiki_links(m.group(1))
        result.append((day_num, links))
    return result


def _get_special_day_entries(block: SpecialDayBlock) -> list[str]:
    """Extract wiki-link titles from a special day block."""
    m = _CONTENT_BLOCK_RE.search(block.raw_accordion_item)
    if not m:
        return []
    return _extract_wiki_links(m.group(2))


# ── Public query API ───────────────────────────────────────────────────────────


def get_entries(  # noqa: C901
    page: CalendarPage,
    start: CalendarDate,
    end: CalendarDate | None = None,
) -> list[tuple[CalendarDate, list[str]]]:
    """
    Return all calendar entries for the date range [start, end].

    If end is None, returns entries for start only.
    Results are in chronological order.
    Dates with no entries are omitted.
    """
    if end is None:
        end = start

    start_ord = _date_to_ordinal(start)
    end_ord = _date_to_ordinal(end)

    if start_ord > end_ord:
        raise ValueError(f"start date {start} must be before or equal to end date {end}")

    results: list[tuple[CalendarDate, list[str]]] = []

    # Page stores years newest-first; iterate in reverse for chronological output
    for year_block in reversed(page.years):
        year = year_block.year

        # Skip years entirely outside the range
        if (year, 999, 99) < start_ord or (year, 0, 0) > end_ord:
            continue

        # Sort sections by calendar order for chronological output
        sorted_sections = sorted(
            year_block.sections,
            key=lambda s: _calendar_order_key(s.month if isinstance(s, MonthBlock) else s.name),
        )

        for section in sorted_sections:
            if isinstance(section, SpecialDayBlock):
                date = CalendarDate(year=year, month_or_special_day=section.name, day=None)
                if start_ord <= _date_to_ordinal(date) <= end_ord:
                    links = _get_special_day_entries(section)
                    if links:
                        results.append((date, links))
            else:
                for day_num, links in sorted(_get_month_day_entries(section), key=lambda x: x[0]):
                    date = CalendarDate(year=year, month_or_special_day=section.month, day=day_num)
                    if start_ord <= _date_to_ordinal(date) <= end_ord and links:
                        results.append((date, links))

    return results


# ── Mutation helpers ───────────────────────────────────────────────────────────


def is_leap_year(year: int) -> bool:
    """
    Return True if year is a leap year in the Forgotten Realms calendar.

    Leap years are divisible by 4 starting from 0 DR: 0, 4, 8 … 1372, 1376 …
    Shieldmeet only occurs in leap years.
    """
    return year % 4 == 0


def _insert_link_in_month(raw_accordion_item: str, day: int, link: str) -> str:
    """
    Insert a wiki link into the date-content div for the given day number.

    Handles both well-formed cells (with </div> before date-number) and
    malformed cells (no closing </div>). Dirty cells are rendered well-formed.
    """
    pattern = re.compile(
        r'(<div class="date-content">)(.*?)(?:</div>\s*)?'
        r"(<div class=\"date-number\">\s*" + re.escape(str(day)) + r"\s*</div>)",
        re.DOTALL,
    )

    found = False

    def replacer(m: re.Match[str]) -> str:
        nonlocal found
        found = True
        opening = m.group(1)
        content = m.group(2)
        day_num_block = m.group(3)

        # Strip closing </div> if present at end of content (well-formed cells)
        content_stripped = re.sub(r"\s*</div>\s*$", "", content, flags=re.DOTALL)
        content_text = content_stripped.rstrip()

        new_content = f"{content_text}\n{link}\n                " if content_text else f"\n{link}\n                "

        return f"{opening}{new_content}</div>\n                {day_num_block}"

    result = pattern.sub(replacer, raw_accordion_item, count=1)
    if not found:
        raise ValueError(f"Day {day} not found in month block")
    return result


def _insert_link_in_special_day(raw_accordion_item: str, link: str) -> str:
    """Insert a wiki link into a special day accordion item's [content] block."""

    def replacer(m: re.Match[str]) -> str:
        content = m.group(2).rstrip()
        new_content = f"\n{content}\n{link}\n" if content.strip() else f"\n{link}\n"
        return m.group(1) + new_content + m.group(3)

    return _CONTENT_BLOCK_RE.sub(replacer, raw_accordion_item, count=1)


def _new_month_accordion_item(month: str) -> str:
    """Generate a new empty 30-cell month accordion item."""
    cell_template = (
        '        <td class="date">\n'
        '            <div class="date-cell">\n'
        '                <div class="date-content">\n'
        "                </div>\n"
        '                <div class="date-number">\n'
        "                    {day}\n"
        "                </div>\n"
        "            </div>\n"
        "        </td>"
    )
    cells = [cell_template.format(day=d) for d in range(1, 31)]

    rows: list[str] = []
    for row_start in range(0, 30, 10):
        row_cells = "\n".join(cells[row_start : row_start + 10])
        rows.append(f"    <tr>\n{row_cells}\n    </tr>")

    table = (
        '<table id="calendar" align="center" border="1" cellpadding="2" cellspacing="5"\n'
        '       style="width:1000px; table-layout: fixed">\n'
        "    <tbody>\n" + "\n".join(rows) + "\n    </tbody>\n</table>"
    )

    return f"[accordion-item] [title]{month}[end-title] [content]\n{table}\n[end-content] [end-accordion-item]\n"


def _new_special_day_accordion_item(name: str) -> str:
    """Generate a new empty special day accordion item."""
    return f"[accordion-item] [title]{name}[end-title] [content]\n[end-content] [end-accordion-item]\n"


def _new_year_block(year: int) -> YearBlock:
    """Generate a new empty year block."""
    return YearBlock(
        year=year,
        raw_pre_sections=f"h2. {year}\n[accordion] \n",
        sections=[],
        raw_post_sections="[end-accordion]\n\n\n\n",
    )


def _get_or_create_year(page: CalendarPage, year: int) -> YearBlock:
    """Find an existing year block or create a new one (most-recent-first order)."""
    for y in page.years:
        if y.year == year:
            return y
    new_year = _new_year_block(year)
    # Insert so that years remain sorted newest-first
    insert_idx = len(page.years)
    for i, y in enumerate(page.years):
        if y.year < year:
            insert_idx = i
            break
    page.years.insert(insert_idx, new_year)
    return new_year


def _get_or_create_section(
    year_block: YearBlock,
    name: str,
) -> MonthBlock | SpecialDayBlock:
    """Find an existing section or create one in the correct calendar-order position."""
    for section in year_block.sections:
        section_name = section.month if isinstance(section, MonthBlock) else section.name
        if section_name == name:
            return section

    # Create new section
    new_section: MonthBlock | SpecialDayBlock
    if name in _MONTHS_SET:
        new_section = MonthBlock(month=name, raw_accordion_item=_new_month_accordion_item(name))
    else:
        new_section = SpecialDayBlock(name=name, raw_accordion_item=_new_special_day_accordion_item(name))

    # Insert in correct calendar-order position among existing sections
    name_order = _calendar_order_key(name)
    insert_idx = len(year_block.sections)
    for i, section in enumerate(year_block.sections):
        s_name = section.month if isinstance(section, MonthBlock) else section.name
        if _calendar_order_key(s_name) > name_order:
            insert_idx = i
            break
    year_block.sections.insert(insert_idx, new_section)
    return new_section


# ── Public mutation API ────────────────────────────────────────────────────────


def add_entry(page: CalendarPage, date: CalendarDate, title: str) -> None:
    """
    Add a wiki-link entry to the specified calendar date.

    The link is recorded as [[title | title]].
    Multiple entries on the same date are appended; existing content is preserved.
    Creates the year, month, or special-day section if it does not yet exist.

    Raises ValueError if:
    - Shieldmeet is requested for a non-leap year
    - A regular month day is requested without a day number
    - A special day is requested with a day number
    """
    name = date.month_or_special_day

    if name == "Shieldmeet" and not is_leap_year(date.year):
        raise ValueError(
            f"Year {date.year} is not a leap year; Shieldmeet does not occur "
            f"(leap years are divisible by 4: 0, 4, 8 … 1372, 1376 …).",
        )

    if name in _SPECIAL_DAYS_SET and date.day is not None:
        raise ValueError(f"{name} is a special day and does not have a day number; omit day.")

    if name in _MONTHS_SET and date.day is None:
        raise ValueError(f"{name} is a regular month; a day number (1-30) must be specified.")

    link = f"[[{title} | {title}]]"
    year_block = _get_or_create_year(page, date.year)
    section = _get_or_create_section(year_block, name)

    if isinstance(section, SpecialDayBlock):
        section.raw_accordion_item = _insert_link_in_special_day(section.raw_accordion_item, link)
    else:
        section.raw_accordion_item = _insert_link_in_month(section.raw_accordion_item, date.day, link)  # type: ignore[arg-type]
