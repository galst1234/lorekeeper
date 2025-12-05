import asyncio

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams
from requests_oauthlib import OAuth1Session
from sentence_transformers import SentenceTransformer

from config import CAMPAIGN_ID, QDRANT_COLLECTION_NAME, QDRANT_URL, VECTOR_NAME
from obsidian_portal.auth import get_authenticated_session_async
from obsidian_portal.ingest import Document, prepare_document_points, upsert_points


async def main() -> None:
    qdrant_client = await _setup_qdrant()
    print("Setting up authenticated session...")
    session = await get_authenticated_session_async()
    docs = await fetch_wiki_pages(session, CAMPAIGN_ID)
    embed_model = await _load_embedding_model()
    await _ingest_documents(docs, embed_model, qdrant_client)


async def _setup_qdrant() -> AsyncQdrantClient:
    print("Initializing Qdrant client...")
    qdrant_client = AsyncQdrantClient(url=QDRANT_URL)
    print("Setting up Qdrant collection...")
    if await qdrant_client.collection_exists(QDRANT_COLLECTION_NAME):
        await qdrant_client.delete_collection(QDRANT_COLLECTION_NAME)
        print("Deleted existing collection.")

    await qdrant_client.create_collection(
        collection_name=QDRANT_COLLECTION_NAME,
        vectors_config={
            VECTOR_NAME: VectorParams(size=384, distance=Distance.COSINE),
        },
    )
    print("Qdrant collection is ready.")
    return qdrant_client


async def fetch_wiki_pages(session: OAuth1Session, campaign_id: str) -> list[Document]:
    url = f"https://api.obsidianportal.com/v1/campaigns/{campaign_id}/wikis.json"
    print(f"Fetching wiki pages from Obsidian Portal API: {url}")
    response = await asyncio.to_thread(session.get, url)
    print(f"API response status: {response.status_code}")
    raw = await asyncio.to_thread(response.json)
    print(f"Fetched {len(raw)} wiki pages.")

    print("Transforming and ingesting documents...")
    docs = [
        Document(
            id=item["id"],
            type=item["type"],
            title=item["name"],
            content=item["body"],
            source_url=item["wiki_page_url"],
            tags=item["tags"],
            gm_only=item["is_game_master_only"],
            created_at=item["created_at"],
            updated_at=item["updated_at"],
        )
        for item in raw
    ]
    return docs


async def _load_embedding_model() -> SentenceTransformer:
    print("Setting up embedding model...")
    embed_model = await asyncio.to_thread(SentenceTransformer, "sentence-transformers/all-MiniLM-L6-v2")
    return embed_model


async def _ingest_documents(
        docs: list[Document],
        embed_model: SentenceTransformer,
        qdrant_client: AsyncQdrantClient,
) -> None:
    for i, doc in enumerate(docs):
        print(f"Processing document {i + 1}")
        points = await asyncio.to_thread(prepare_document_points, doc, embed_model)
        await upsert_points(qdrant_client, collection_name=QDRANT_COLLECTION_NAME, points=points)


if __name__ == "__main__":
    asyncio.run(main())
