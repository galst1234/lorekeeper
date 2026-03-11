import asyncio

from fastmcp import FastMCP
from requests_oauthlib import OAuth1Session

import config
from obsidian_portal.api import create_character, fetch_character, fetch_characters, fetch_wiki_page
from obsidian_portal.auth import get_authenticated_session_async
from obsidian_portal.models import Character, CharacterRequest, Page

_CAMPAIGN_ID = config.CAMPAIGN_ID

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
) -> None:
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
        bio (str): A brief introductory outline, and any information you deem important to get a quick understanding of whom the character is.
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
    await create_character(session, campaign_id, character_request)


@mcp.tool()
def ping(message: str = "pong") -> str:
    """Simple connectivity check for the Obsidian Portal MCP."""
    return f"Obsidian Portal MCP: {message}"


if __name__ == "__main__":
    asyncio.run(mcp.run_async(transport="streamable-http", host="0.0.0.0", port=8080))
