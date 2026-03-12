import asyncio

from fastmcp import FastMCP
from requests_oauthlib import OAuth1Session

import config
from obsidian_portal.api import (
    create_character,
    create_quest,
    fetch_character,
    fetch_characters,
    fetch_quests,
    fetch_wiki_page,
    update_quest,
)
from obsidian_portal.auth import get_authenticated_session_async
from obsidian_portal.models import Character, CharacterRequest, Page, Quest, QuestStatus, QuestType

_CAMPAIGN_ID = config.CAMPAIGN_ID
_QUEST_LOG_PAGE_ID = config.QUEST_LOG_PAGE_ID

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


# @mcp.tool(tags={"WikiPage", "Post"})
# async def fetch_wiki_pages(campaign_id: str) -> list[Page]:
#     """
#     Fetch wiki pages from Obsidian Portal for the specified campaign ID.
#
#     Args:
#         campaign_id (str): The ID of the campaign to fetch wiki pages from.
#
#     Returns:
#         list[Page]: A list of wiki pages.
#     """
#
#     session = await _get_session()
#     return await fetcher_fetch_wiki_pages(session, campaign_id)


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


@mcp.tool()
def ping(message: str = "pong") -> str:
    """Simple connectivity check for the Obsidian Portal MCP."""
    return f"Obsidian Portal MCP: {message}"


if __name__ == "__main__":
    asyncio.run(mcp.run_async(transport="streamable-http", host="0.0.0.0", port=8080))
