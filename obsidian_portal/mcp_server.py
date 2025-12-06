import asyncio

from fastmcp import FastMCP
from requests_oauthlib import OAuth1Session

from obsidian_portal.auth import get_authenticated_session_async
from obsidian_portal.fetcher import fetch_character as fetcher_fetch_character
from obsidian_portal.fetcher import fetch_characters as fetcher_fetch_characters
from obsidian_portal.fetcher import fetch_wiki_page as fetcher_fetch_wiki_page
from obsidian_portal.fetcher import fetch_wiki_pages as fetcher_fetch_wiki_pages
from obsidian_portal.ingest import Character, Page

mcp = FastMCP(
    name="obsidian-portal",
    instructions="""
        This MCP provides tools to fetch wiki pages and character information from Obsidian Portal campaigns.
        Use the provided tools to retrieve the necessary data based on campaign and page/character IDs.
    """,
)


_session: OAuth1Session | None = None


async def _get_session() -> OAuth1Session:
    global _session  # noqa: PLW0603
    if _session is None:
        _session = await get_authenticated_session_async()
    return _session


@mcp.tool(tags={"WikiPage", "Post"})
async def fetch_wiki_pages(campaign_id: str) -> list[Page]:
    """
    Fetch wiki pages from Obsidian Portal for the specified campaign ID.

    Args:
        campaign_id (str): The ID of the campaign to fetch wiki pages from.

    Returns:
        list[Page]: A list of wiki pages.
    """

    session = await _get_session()
    return await fetcher_fetch_wiki_pages(session, campaign_id)


@mcp.tool(tags={"WikiPage", "Post"})
async def fetch_wiki_page(campaign_id: str, page_id: str) -> Page:
    """
    Fetch a specific wiki page from Obsidian Portal for the specified campaign ID and page ID.

    Args:
        campaign_id (str): The ID of the campaign.
        page_id (str): The ID of the wiki page to fetch.

    Returns:
        Page: The wiki page.
    """
    session = await _get_session()
    return await fetcher_fetch_wiki_page(session, campaign_id, page_id)


@mcp.tool(tags={"Character"})
async def fetch_characters(campaign_id: str) -> list[Character]:
    """
    Fetch characters from Obsidian Portal for the specified campaign ID.

    Note: To conserve bandwidth, the bio and description fields are not returned.
    If you need the full text of these fields you will need to retrieve the pages individually using
    the `fetch_character` tool.

    Args:
        campaign_id (str): The ID of the campaign to fetch characters from.

    Returns:
        list[Character]: A list of characters.
    """
    session = await _get_session()
    return await fetcher_fetch_characters(session, campaign_id)


@mcp.tool(tags={"Character"})
async def fetch_character(campaign_id: str, character_id: str) -> Character:
    """
    Fetch a specific character from Obsidian Portal for the specified campaign ID and character ID.

    Args:
        campaign_id (str): The ID of the campaign.
        character_id (str): The ID of the character to fetch.

    Returns:
        Character: The character.
    """
    session = await _get_session()
    return await fetcher_fetch_character(session, campaign_id, character_id)


@mcp.tool()
def ping(message: str = "pong") -> str:
    """Simple connectivity check for the Obsidian Portal MCP."""
    return f"Obsidian Portal MCP: {message}"


if __name__ == "__main__":
    asyncio.run(mcp.run_async(transport="streamable-http", port=8080))
