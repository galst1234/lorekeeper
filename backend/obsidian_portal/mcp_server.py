import asyncio
import re

from fastmcp import FastMCP
from requests_oauthlib import OAuth1Session

from config import settings
from obsidian_portal.api import (
    create_character,
    create_quest,
    fetch_character,
    fetch_characters,
    fetch_quests,
    fetch_wiki_page,
    fetch_wiki_pages,
    update_quest,
    update_wiki_page,
)
from obsidian_portal.auth import get_authenticated_session_async
from obsidian_portal.calendar_api import add_calendar_entry, fetch_calendar_entries
from obsidian_portal.calendar_parser import CalendarDate
from obsidian_portal.models import Character, CharacterRequest, Page, PageSummary, Quest, QuestStatus, QuestType

_WIKI_LINK_REGEX = re.compile(r"\[\[[^]]*]]")


_CAMPAIGN_ID = settings.campaign_id
_QUEST_LOG_PAGE_ID = settings.quest_log_page_id
_CALENDAR_PAGE_ID = settings.calendar_page_id

mcp = FastMCP(
    name="obsidian-portal",
    instructions="""
        This MCP provides tools to fetch wiki pages and character information from Obsidian Portal campaigns.
        Use the provided tools to retrieve the necessary data based on campaign and page/character IDs.
        The IDs are NOT the names, titles, or slugs, but the unique identifiers assigned by Obsidian Portal,
         which are a 32 character hex strings.
    """,
)


_session: OAuth1Session | None = None


async def _get_session() -> OAuth1Session:
    global _session  # noqa: PLW0603
    if _session is None:
        _session = await get_authenticated_session_async()
    return _session


@mcp.tool(tags={"WikiPage", "Post"})
async def fetch_wiki_pages_tool(campaign_id: str = _CAMPAIGN_ID) -> list[PageSummary]:
    """
    Fetch a summary of all wiki pages in the campaign (id, slug, title, tags).

    Use this to build an entity catalog for link resolution. Bodies are excluded —
    use `fetch_wiki_page_tool` if you need the full content of a specific page.

    Args:
        campaign_id (str): The campaign ID — pre-filled, do not supply.

    Returns:
        list[PageSummary]: All wiki pages with id, slug, title, tags, and gm_only flag.
    """
    session = await _get_session()
    pages = await fetch_wiki_pages(session, campaign_id)
    return [PageSummary.model_validate(p.model_dump(by_alias=False)) for p in pages]


@mcp.tool(tags={"WikiPage", "Post"})
async def fetch_wiki_page_tool(page_id: str, campaign_id: str = _CAMPAIGN_ID) -> Page:
    """
    Fetch a specific wiki page from Obsidian Portal for the specified campaign ID by page ID.

    IMPORTANT: ONLY use it when you need the FULL content of a specific page. It is better than fully expanding chunks
    of a page retrieved in search results, and should be used instead of expansion when you know you need the full
    content of a page.

    Args:
        page_id (str): The ID of the wiki page to fetch.
        campaign_id (str): The campaign ID — pre-filled, do not supply.

    Returns:
        Page: The wiki page.
    """
    session = await _get_session()
    return await fetch_wiki_page(session, campaign_id, page_id)


@mcp.tool(tags={"WikiPage", "AdventureLog"})
async def inject_adventure_log_links_tool(
    page_id: str,
    entity_links: dict[str, str],
    campaign_id: str = _CAMPAIGN_ID,
) -> str:
    """
    Inject wiki-link syntax into an adventure log entry for the first appearance of each entity.

    Only the first occurrence of each mention is linked. Entities already linked anywhere
    in the text are skipped entirely. No other changes are made to the text.

    IMPORTANT: Before calling this tool you MUST:
    1. Call `fetch_characters_tool` to get all characters with their slugs.
    2. Call `fetch_wiki_pages_tool` to get all wiki pages with their titles.
    3. Call `fetch_wiki_page_tool(page_id)` to get the adventure log entry body.
    4. Analyze the body text against the entity catalog. For each entity whose name (or a
       shortened/informal form of it) appears in the text, record:
       - mention_text: the EXACT substring as it appears in the entry
       - target: ":slug" for characters, "Page Title" for pages
    5. Show the user the planned links in a concise list:
         "mention_text" → wiki-link
       and ask for explicit confirmation before proceeding.
    6. Only call this tool after receiving explicit approval.

    Args:
        page_id (str): The ID of the adventure log wiki page to update.
        entity_links (dict[str, str]): Mapping of exact mention text (as it appears in the
            entry) to the bare link target — do NOT include [[ or ]].
            Use ":slug" for characters, "Page Title" for pages.
            The tool builds the [[...]] syntax itself. Example:
            {"Allandra": ":allandra-grey",
             "the inn": "The Rusty Flagon",
             "Steel Dragon": "Steel Dragon inn, the"}
        campaign_id (str): The campaign ID — pre-filled, do not supply.

    Returns:
        str: Summary of links applied and any skipped entities.
    """
    session = await _get_session()
    page = await fetch_wiki_page(session, campaign_id, page_id)
    body = page.body

    applied: list[str] = []
    skipped: list[str] = []

    for mention, raw_target in entity_links.items():
        # Strip [[...]] if GPT accidentally included them
        target = raw_target.strip().removeprefix("[[").removesuffix("]]")
        link = f"[[{target} | {mention}]]"

        already_linked = bool(
            re.search(r"\[\[\s*" + re.escape(target) + r"\s*\|[^]]*]]", body, re.IGNORECASE),
        )
        if already_linked:
            skipped.append(mention)
            continue

        protected = [(m.start(), m.end()) for m in _WIKI_LINK_REGEX.finditer(body)]
        mention_re = re.compile(r"\b" + re.escape(mention) + r"\b", re.IGNORECASE)
        replaced = False
        for match in mention_re.finditer(body):
            if not any(start <= match.start() < end for start, end in protected):
                body = body[: match.start()] + link + body[match.end() :]
                applied.append(f'"{mention}" → {link}')
                replaced = True
                break
        if not replaced:
            skipped.append(mention)

    if not applied:
        return "No links were applied. Entities may already be linked or not found in text."

    await update_wiki_page(session, campaign_id, page_id, body=body)

    result = f"Applied {len(applied)} link(s):\n" + "\n".join(applied)
    if skipped:
        result += f"\n\nSkipped (already linked or not found): {', '.join(skipped)}"
    return result


@mcp.tool(tags={"Character"})
async def fetch_characters_tool(campaign_id: str = _CAMPAIGN_ID) -> list[Character]:
    """
    Fetch characters from Obsidian Portal for the specified campaign ID.

    Note: To conserve bandwidth, the bio and description fields are not returned.
    If you need the full text of these fields you need to retrieve the pages individually using `fetch_character_tool`.

    Args:
        campaign_id (str): The campaign ID — pre-filled, do not supply.

    Returns:
        list[Character]: A list of characters.
    """
    session = await _get_session()
    return await fetch_characters(session, campaign_id)


@mcp.tool(tags={"Character"})
async def fetch_character_tool(character_id: str, campaign_id: str = _CAMPAIGN_ID) -> Character:
    """
    Fetch a specific character from Obsidian Portal for the specified campaign ID by character ID.

    Use this when you need the full bio and description of a specific character.

    Args:
        character_id (str): The ID of the character to fetch.
        campaign_id (str): The campaign ID — pre-filled, do not supply.

    Returns:
        Character: The character.
    """
    session = await _get_session()
    return await fetch_character(session, campaign_id, character_id)


@mcp.tool(tags={"Character"})
async def create_character_tool(  # noqa: PLR0913, PLR0917
    name: str,
    description: str | None = None,
    bio: str | None = None,
    tagline: str | None = None,
    tags: set[str] | None = None,
    campaign_id: str = _CAMPAIGN_ID,
) -> Character:
    """
    Create a new character in Obsidian Portal for the specified campaign ID.

    IMPORTANT: Before creating a character you MUST first fetch the list of existing characters in the campaign using
    `fetch_characters_tool` and make sure that there isn't already a character with the same name. For consecutive
    character creation, you can fetch the list of characters once and keep it in context to check against before
    creating each character. Do this FIRST before even showing the user the information or generating any content for
    the character you plan to create, to avoid unnecessary work in case the character already exists.

    IMPORTANT: Before creating a character you MUST first show the user the character's information you plan to create,
    and ask for confirmation that they want to create the character with this information.

    IMPORTANT: Before creating a character MAKE SURE to be concise. Also MAKE SURE you are not repeating information.

    Args:
        name (str): The name of the character.
        description (str): A brief physical description of the character (if available).
            Use Obsidian Portal wiki-link syntax for any referenced entities:
            [[:slug | Display Name]] for characters, [[Page Title | Display Name]] for pages.
        bio (str): A brief introductory outline, and any information you deem important to get a quick understanding of whom the character is.
            Use Obsidian Portal wiki-link syntax for any referenced entities:
            [[:slug | Display Name]] for characters, [[Page Title | Display Name]] for pages.
        tagline (str): A SHORT one sentence description of the character, suitable for use as a tagline or quick reference.
        tags (set[str]): A list of tags to associate with the character. For dead characters MAKE SURE to include the "Dead" tag.
        campaign_id (str): The campaign ID — pre-filled, do not supply.

    Returns:
        None
    """  # noqa: E501
    tags: set[str] = tags or set()
    tags.add("AI Generated")
    session = await _get_session()
    character_request = CharacterRequest(
        name=name,
        description=description,
        bio=bio,
        tagline=tagline,
        tags=list(tags),
    )
    return await create_character(session, campaign_id, character_request)


@mcp.tool(tags={"WikiPage", "Quest"})
async def fetch_quests_tool(campaign_id: str = _CAMPAIGN_ID, page_id: str = _QUEST_LOG_PAGE_ID) -> list[Quest]:
    """
    Fetch all quests from the Quest Log wiki page, parsed into structured objects.

    Use this as the first step before creating or updating a quest — to check for duplicate titles
    and to get the exact current title of a quest you want to modify.
    The Personal Quests section is excluded from results.

    Args:
        campaign_id (str): The campaign ID — pre-filled, do not supply.
        page_id (str): The Quest Log wiki page ID — pre-filled, do not supply.

    Returns:
        list[Quest]: All quests with their title, content, status (open/completed/failed),
            phase (e.g. "Phase 2", "Phase 1"), and quest_type ("Main Quest", "Side Quest", or None).
    """
    session = await _get_session()
    return await fetch_quests(session, campaign_id, page_id)


@mcp.tool(tags={"WikiPage", "Quest"})
async def create_quest_tool(  # noqa: PLR0913, PLR0917
    title: str,
    content: str,
    phase: str,
    quest_type: QuestType | None,
    status: QuestStatus = "open",
    campaign_id: str = _CAMPAIGN_ID,
    page_id: str = _QUEST_LOG_PAGE_ID,
) -> str:
    """
    Add a new quest to the Quest Log wiki page.

    IMPORTANT: Before calling this tool you MUST first use `fetch_quests_tool` to confirm
    no quest with the same title already exists.

    IMPORTANT: Before calling this tool you MUST show the user the quest details (title, content,
    phase, quest_type, status) and ask for explicit confirmation.

    IMPORTANT: Keep quest content concise and avoid repeating information.

    Args:
        title (str): The quest title as it will appear in the accordion header.
        content (str): The quest body text (supports Obsidian Portal markup).
            Use Obsidian Portal wiki-link syntax for any referenced entities:
            [[:slug | Display Name]] for characters, [[Page Title | Display Name]] for pages.
        phase (str): The phase section to place the quest in, e.g. "Phase 2", "Future Phases".
        quest_type (str | None): "Main Quest" or "Side Quest" subsection, or None for phases
            that have no subsection headers (e.g. "Future Phases").
        status (str): "open", "completed", or "failed". Determines active vs completed section.
            Defaults to "open".
        campaign_id (str): The campaign ID — pre-filled, do not supply.
        page_id (str): The Quest Log wiki page ID — pre-filled, do not supply.

    Returns:
        str: Confirmation message with the quest's location and status.
    """
    session = await _get_session()
    await create_quest(
        session,
        campaign_id,
        page_id,
        quest=Quest(title=title, content=content, status=status, phase=phase, quest_type=quest_type),
    )
    return f"Quest '{title}' created in {phase} / {quest_type or 'no sub-section'} ({status})."


@mcp.tool(tags={"WikiPage", "Quest"})
async def update_quest_tool(  # noqa: PLR0913, PLR0917
    title: str,
    new_title: str | None = None,
    new_content: str | None = None,
    new_status: QuestStatus | None = None,
    new_phase: str | None = None,
    new_quest_type: QuestType | None = None,
    campaign_id: str = _CAMPAIGN_ID,
    page_id: str = _QUEST_LOG_PAGE_ID,
) -> str:
    """
    Update an existing quest on the Quest Log wiki page, identified by its current title.
    Only supply the fields you want to change — omitted fields are left as-is.

    Changing status to "completed" or "failed" automatically moves the quest from the
    Active Quests section to the Completed Quests section. Changing phase or quest_type
    will also relocate the quest to the correct subsection.

    IMPORTANT: Before calling this tool you MUST first use `fetch_quests_tool` to confirm
    the quest exists and get its exact current title (titles are case-sensitive).

    IMPORTANT: Before calling this tool you MUST show the user the planned changes and ask
    for explicit confirmation.

    Args:
        title (str): The current exact title of the quest to update.
        new_title (str | None): Rename the quest to this title.
        new_content (str | None): Replace the quest body text.
            Use Obsidian Portal wiki-link syntax for any referenced entities:
            [[:slug | Display Name]] for characters, [[Page Title | Display Name]] for pages.
        new_status (str | None): Change status to "open", "completed", or "failed".
        new_phase (str | None): Move the quest to a different phase section.
        new_quest_type (str | None): Move the quest to "Main Quest" or "Side Quest" subsection.
        campaign_id (str): The campaign ID — pre-filled, do not supply.
        page_id (str): The Quest Log wiki page ID — pre-filled, do not supply.

    Returns:
        str: Human-readable summary of the changes applied.
    """
    session = await _get_session()
    summary = await update_quest(
        session,
        campaign_id,
        page_id,
        title=title,
        new_title=new_title,
        new_content=new_content,
        new_status=new_status,
        new_phase=new_phase,
        new_quest_type=new_quest_type,
    )
    return f"Quest '{title}' updated: {summary}"


@mcp.tool(tags={"WikiPage", "Calendar"})
async def fetch_calendar_entries_tool(  # noqa: PLR0913, PLR0917
    start_year: int,
    start_month_or_special_day: str,
    start_day: int | None = None,
    end_year: int | None = None,
    end_month_or_special_day: str | None = None,
    end_day: int | None = None,
    campaign_id: str = _CAMPAIGN_ID,
    page_id: str = _CALENDAR_PAGE_ID,
) -> list[tuple[CalendarDate, list[str]]]:
    """
    Fetch adventure log summaries recorded on the campaign calendar.

    For a single regular day:
      - start_month_or_special_day = month name (e.g. "Kythorn")
      - start_day = day number (1-30)

    For a single special day (falls between months, not inside them):
      - start_month_or_special_day = special day name (see list below)
      - start_day = omit

    For a date range: also provide end_year, end_month_or_special_day, and
    end_day (omit end_day for a special day end).

    Special days: "Midwinter" (between Hammer and Alturiak),
                  "Greengrass" (between Tarsakh and Mirtul),
                  "Midsummer" (between Flamerule and Eleasis),
                  "Shieldmeet" (day after Midsummer, once every 4 years: 0, 4 ... 1372, 1376 ...),
                  "Highharvestide" (between Eleint and Marpenoth),
                  "Feast of the Moon" (between Uktar and Nightal)

    Args:
        start_year (int): Year of the start date.
        start_month_or_special_day (str): Month name or special day name for the start date.
        start_day (int | None): Day number (1-30) for a regular month start; omit for special days.
        end_year (int | None): Year of the end date; omit for a single-date query.
        end_month_or_special_day (str | None): Month or special day for the end date; omit for single-date.
        end_day (int | None): Day number for end date if it is a regular month; omit for special days.
        campaign_id (str): The campaign ID - pre-filled, do not supply.
        page_id (str): The Calendar wiki page ID - pre-filled, do not supply.

    Returns:
        list of (CalendarDate, [summary_titles]) for every date in the range that has entries.
    """
    session = await _get_session()
    start = CalendarDate(year=start_year, month_or_special_day=start_month_or_special_day, day=start_day)
    end: CalendarDate | None = None
    if end_year is not None and end_month_or_special_day is not None:
        end = CalendarDate(year=end_year, month_or_special_day=end_month_or_special_day, day=end_day)
    return await fetch_calendar_entries(session, start, end, campaign_id=campaign_id, page_id=page_id)


@mcp.tool(tags={"WikiPage", "Calendar"})
async def add_calendar_entry_tool(  # noqa: PLR0913, PLR0917
    month_or_special_day: str,
    summary_title: str,
    day: int | None = None,
    year: int | None = None,
    campaign_id: str = _CAMPAIGN_ID,
    page_id: str = _CALENDAR_PAGE_ID,
) -> str:
    """
    Add an adventure log summary link to a specific date on the campaign calendar.

    The link is recorded as [[summary_title | summary_title]] on the given date.
    Multiple summaries can share the same date - they are appended, not overwritten.
    If the month or special day does not yet exist in the calendar, it is created automatically.
    Always add to the first in-game day of the summary's events.

    For a regular month day:
      - month_or_special_day = month name (e.g. "Kythorn")
      - day = day number (1-30)

    For a special day (falls between months, not inside them):
      - month_or_special_day = the special day name exactly as listed below
      - day = omit (leave as None)

    Special days: "Midwinter" (between Hammer and Alturiak),
                  "Greengrass" (between Tarsakh and Mirtul),
                  "Midsummer" (between Flamerule and Eleasis),
                  "Shieldmeet" (day after Midsummer, once every 4 years: 0, 4 ... 1372, 1376 ...),
                  "Highharvestide" (between Eleint and Marpenoth),
                  "Feast of the Moon" (between Uktar and Nightal)

    IMPORTANT: NEVER ask the user for the in-game date. Before calling this tool:
    1. Fetch the summary's wiki page using fetch_wiki_page_tool (use qdrant-find to locate
       the page ID by title if you do not already have it).
    2. Read the page body to identify the first in-game date of the session (month, day,
       and year in the Forgotten Realms Calendar of Harptos).
       If the summary does not explicitly state a year, assume the most recent year in the calendar.
    3. Show the user ONE confirmation line in exactly this form and wait for explicit approval
       (a clear "yes", "confirm", "ok", or equivalent) before proceeding:
         "Add <title> to <month_or_special_day> <day>, <year>?"
    4. Only call this tool after receiving that explicit approval.
    Do NOT treat a menu choice or year selection as confirmation - always show the final resolved
    entry and require a separate explicit "yes" before calling the tool.

    Args:
        month_or_special_day (str): Month name or special day name.
        summary_title (str): The exact title of the adventure log summary wiki page.
        day (int | None): Day number (1-30) for a regular month; omit for special days.
        year (int | None): Year to add the entry to. If omitted, uses the most recent year
            present in the calendar - only supply when adding to a past year.
        campaign_id (str): The campaign ID - pre-filled, do not supply.
        page_id (str): The Calendar wiki page ID - pre-filled, do not supply.

    Returns:
        str: Confirmation message with the date the entry was added to.
    """
    session = await _get_session()
    resolved_year = await add_calendar_entry(
        session,
        month_or_special_day=month_or_special_day,
        day=day,
        title=summary_title,
        year=year,
        campaign_id=campaign_id,
        page_id=page_id,
    )
    day_str = f" {day}" if day is not None else ""
    return f"Added '[[{summary_title} | {summary_title}]]' to {month_or_special_day}{day_str}, {resolved_year}."


@mcp.tool()
def ping(message: str = "pong") -> str:
    """Simple connectivity check for the Obsidian Portal MCP."""
    return f"Obsidian Portal MCP: {message}"


if __name__ == "__main__":
    asyncio.run(mcp.run_async(transport="streamable-http", host="0.0.0.0", port=8080))
