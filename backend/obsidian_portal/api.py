import asyncio

from requests_oauthlib import OAuth1Session

from obsidian_portal.models import Character, CharacterRequest, Page


async def fetch_wiki_pages(session: OAuth1Session, campaign_id: str) -> list[Page]:
    url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/wikis.json"
    print(f"Fetching wiki pages from Obsidian Portal API: {url}")
    response = await asyncio.to_thread(session.get, url)
    print(f"API response status: {response.status_code}")
    raw = await asyncio.to_thread(response.json)
    print(f"Fetched {len(raw)} wiki pages.")

    print("Transforming and ingesting documents...")
    return [Page.model_validate(item) for item in raw]


async def fetch_wiki_page(session: OAuth1Session, campaign_id: str, page_id: str) -> Page:
    url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/wikis/{page_id}.json"
    print(f"Fetching wiki page {page_id} from Obsidian Portal API: {url}")
    response = await asyncio.to_thread(session.get, url)
    print(f"API response status: {response.status_code}")
    raw = await asyncio.to_thread(response.json)
    return Page.model_validate(raw)


async def fetch_characters(session: OAuth1Session, campaign_id: str, enrich: bool = False) -> list[Character]:
    characters_url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/characters.json"
    print(f"Fetching characters from Obsidian Portal API: {characters_url}")
    characters_response = await asyncio.to_thread(session.get, characters_url)
    print(f"API response status: {characters_response.status_code}")
    characters_raw = await asyncio.to_thread(characters_response.json)
    print(f"Fetched {len(characters_raw)} characters.")

    if enrich:
        return [await fetch_character(session, campaign_id, character_raw["id"]) for character_raw in characters_raw]
    return [Character.model_validate(item) for item in characters_raw]


async def fetch_character(session: OAuth1Session, campaign_id: str, character_id: str) -> Character:
    url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/characters/{character_id}.json"
    print(f"Fetching character {character_id} from Obsidian Portal API: {url}")
    response = await asyncio.to_thread(session.get, url)
    print(f"API response status: {response.status_code}")
    raw = await asyncio.to_thread(response.json)
    return Character.model_validate(raw)


async def create_character(session: OAuth1Session, campaign_id: str, character: CharacterRequest) -> None:
    """We don't return any value because for some reason the API returns 500 even on success, fun!"""
    url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/characters.json"
    data = {"character": character.model_dump(by_alias=True)}
    print(f"Creating character in Obsidian Portal API: {url} with data: {data}")
    response = await asyncio.to_thread(session.post, url, json=data)
    print(f"API response status: {response.status_code}")
