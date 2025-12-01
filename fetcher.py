from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from sentence_transformers import SentenceTransformer

from auth import get_authenticated_session
from config import CAMPAIGN_ID, QDRANT_COLLECTION_NAME, QDRANT_URL, VECTOR_NAME
from ingest import Document, prepare_document_points, upsert_points


def main():
    print("Initializing Qdrant client...")
    qdrant_client = QdrantClient(url=QDRANT_URL)
    print("Setting up Qdrant collection...")
    if qdrant_client.collection_exists(QDRANT_COLLECTION_NAME):
        qdrant_client.delete_collection(QDRANT_COLLECTION_NAME)
        print("Deleted existing collection.")

    qdrant_client.create_collection(
        collection_name=QDRANT_COLLECTION_NAME,
        vectors_config={
            VECTOR_NAME: VectorParams(
                size=384,
                distance=Distance.COSINE
            ),
        },
    )
    print("Qdrant collection is ready.")

    print("Setting up authenticated session...")
    session = get_authenticated_session()
    url = f"https://api.obsidianportal.com/v1/campaigns/{CAMPAIGN_ID}/wikis.json"
    print(f"Fetching wiki pages from Obsidian Portal API: {url}")
    response = session.get(url)
    print(f"API response status: {response.status_code}")
    raw = response.json()
    print(f"Fetched {len(raw)} wiki pages.")

    print("Transforming and ingesting documents...")
    docs = [
        Document(
            id=item['id'],
            type=item['type'],
            title=item['name'],
            content=item['body'],
            source_url=item['wiki_page_url'],
            tags=item['tags'],
            gm_only=item['is_game_master_only'],
            created_at=item['created_at'],
            updated_at=item['updated_at'],
        )
        for item in raw
    ]

    print("Setting up embedding model...")
    embed_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    for i, doc in enumerate(docs):
        print(f"Processing document {i + 1}")
        points = prepare_document_points(doc, embed_model)
        upsert_points(qdrant_client, collection_name=QDRANT_COLLECTION_NAME, points=points)


if __name__ == "__main__":
    main()
