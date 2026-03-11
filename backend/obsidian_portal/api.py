import asyncio

from requests_oauthlib import OAuth1Session

from obsidian_portal.models import Character, CharacterRequest, Page, Quest, QuestStatus, QuestType
from obsidian_portal.quest_parser import (
    extract_quests,
    insert_quest,
    parse_body,
    render_body,
    update_quest_data,
)


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


async def update_wiki_page(
    session: OAuth1Session,
    campaign_id: str,
    page_id: str,
    *,
    body: str,
) -> None:
    url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/wikis/{page_id}.json"
    data = {"wiki_page": {"body": body}}
    print(f"Updating wiki page {page_id}: {url}")
    response = await asyncio.to_thread(session.put, url, json=data)
    print(f"API response status: {response.status_code}")
    response.raise_for_status()


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


async def fetch_quests(session: OAuth1Session, campaign_id: str, quest_page_id: str) -> list[Quest]:
    page = await fetch_wiki_page(session, campaign_id, quest_page_id)
    return extract_quests(parse_body(page.body))


async def create_quest(
    session: OAuth1Session,
    campaign_id: str,
    quest_page_id: str,
    *,
    quest: Quest,
) -> None:
    page = await fetch_wiki_page(session, campaign_id, quest_page_id)
    parsed = parse_body(page.body)
    insert_quest(parsed, quest)
    await update_wiki_page(session, campaign_id, quest_page_id, body=render_body(parsed))


async def update_quest(  # noqa: PLR0913
    session: OAuth1Session,
    campaign_id: str,
    quest_page_id: str,
    *,
    title: str,
    new_title: str | None = None,
    new_content: str | None = None,
    new_status: QuestStatus | None = None,
    new_phase: str | None = None,
    new_quest_type: QuestType | None = None,
) -> str:
    page = await fetch_wiki_page(session, campaign_id, quest_page_id)
    parsed = parse_body(page.body)
    summary = update_quest_data(
        parsed,
        title,
        new_title=new_title,
        new_content=new_content,
        new_status=new_status,
        new_phase=new_phase,
        new_quest_type=new_quest_type,
    )
    await update_wiki_page(session, campaign_id, quest_page_id, body=render_body(parsed))
    return summary
