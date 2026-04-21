"""Async API functions for reading and updating the campaign calendar."""

from __future__ import annotations

from requests_oauthlib import OAuth1Session

from lorekeeper.config import settings
from lorekeeper.obsidian_portal.api import fetch_wiki_page, update_wiki_page
from lorekeeper.obsidian_portal.calendar_parser import CalendarDate, add_entry, get_entries, parse_body, render_body


async def fetch_calendar_entries(
    session: OAuth1Session,
    start: CalendarDate,
    end: CalendarDate | None = None,
    *,
    campaign_id: str = settings.campaign_id,
    page_id: str = settings.calendar_page_id,
) -> list[tuple[CalendarDate, list[str]]]:
    """
    Fetch calendar entries for a date or date range.

    Returns a list of (date, [summary_titles]) for every date in the range that has entries.
    Results are in chronological order. Dates with no entries are omitted.
    """
    page_data = await fetch_wiki_page(session, campaign_id, page_id)
    calendar = parse_body(page_data.body)
    return get_entries(calendar, start, end)


async def add_calendar_entry(  # noqa: PLR0913
    session: OAuth1Session,
    *,
    month_or_special_day: str,
    day: int | None,
    title: str,
    year: int | None = None,
    campaign_id: str = settings.campaign_id,
    page_id: str = settings.calendar_page_id,
) -> int:
    """
    Add a summary link to the specified calendar date and persist the change.

    If year is None, the most recent year present in the calendar is used.
    Returns the resolved year (useful when year was None).

    Raises ValueError for invalid date combinations (e.g. Shieldmeet in a non-leap year).
    """
    page_data = await fetch_wiki_page(session, campaign_id, page_id)
    calendar = parse_body(page_data.body)

    resolved_year = year if year is not None else calendar.years[0].year

    date = CalendarDate(year=resolved_year, month_or_special_day=month_or_special_day, day=day)
    add_entry(calendar, date, title)
    await update_wiki_page(session, campaign_id, page_id, body=render_body(calendar))
    return resolved_year
