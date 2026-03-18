import asyncio
import json
from datetime import UTC, datetime

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from config import settings
from obsidian_portal.api import fetch_characters, fetch_wiki_pages
from obsidian_portal.auth import get_authenticated_session_async
from obsidian_portal.ingest import prepare_document_points, upsert_points
from obsidian_portal.models import Document


async def main() -> None:
    fetched_at = datetime.now(UTC)
    qdrant_client = await _setup_qdrant()
    print("Setting up authenticated session...")
    session = await get_authenticated_session_async()
    docs: list[Document] = []
    docs += await fetch_wiki_pages(session, settings.campaign_id)
    docs += await fetch_characters(session, settings.campaign_id, enrich=True)
    embed_model = _load_embedding_model()
    await _ingest_documents(docs, embed_model, qdrant_client)
    (settings.data_dir / "last_fetched.json").write_text(
        json.dumps({"fetched_at": fetched_at.isoformat()}),
        encoding="utf-8",
    )
    print("Wrote last_fetched.json")


async def _setup_qdrant() -> AsyncQdrantClient:
    print("Initializing Qdrant client...")
    qdrant_client = AsyncQdrantClient(url=settings.qdrant_url)
    print("Setting up Qdrant collection...")
    if await qdrant_client.collection_exists(settings.collection_name):
        await qdrant_client.delete_collection(settings.collection_name)
        print("Deleted existing collection.")

    await qdrant_client.create_collection(
        collection_name=settings.collection_name,
        vectors_config={
            settings.vector_name: VectorParams(size=768, distance=Distance.COSINE),
        },
    )
    print("Qdrant collection is ready.")
    return qdrant_client


def _load_embedding_model() -> TextEmbedding:
    print("Loading fastembed model BAAI/bge-base-en-v1.5...")
    return TextEmbedding("BAAI/bge-base-en-v1.5")


async def _ingest_documents(
    docs: list[Document],
    embed_model: TextEmbedding,
    qdrant_client: AsyncQdrantClient,
) -> None:
    for i, doc in enumerate(docs):
        print(f"Processing document {i + 1}")
        points = await asyncio.to_thread(prepare_document_points, doc, embed_model)
        await upsert_points(qdrant_client, collection_name=settings.collection_name, points=points)


if __name__ == "__main__":
    asyncio.run(main())
