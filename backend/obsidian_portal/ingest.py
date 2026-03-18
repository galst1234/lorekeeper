from uuid import uuid4

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from config import settings
from obsidian_portal.models import Document


def chunk_text(text: str, max_chars: int = 800, overlap_chars: int = 150) -> list[str]:
    """
    Split text into paragraphs, then group paragraphs until they reach max_chars.
    Add overlap (in characters) between chunks for better context retention.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    last_chunk = ""

    for p in paragraphs:
        if len(current) + len(p) + 1 <= max_chars:
            current = f"{current}\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
                # Add overlap: take the last overlap_chars from the current chunk
                last_chunk = current[-overlap_chars:] if overlap_chars > 0 else ""
            # Start new chunk with overlap
            current = (last_chunk + "\n" + p).strip() if last_chunk else p

    if current:
        chunks.append(current)

    return chunks


def prepare_document_points(doc: Document, embed_model: TextEmbedding) -> list[PointStruct]:
    print(f"Ingesting document ID: {doc.id}, Type: {doc.type}")
    chunks = chunk_text(doc.content)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i + 1}/{len(chunks)} (Length: {len(chunk)} chars)")

    vectors = list(embed_model.embed(chunks))
    points = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
        point_id = str(uuid4())
        metadata = doc.metadata.copy()
        metadata.update({
            "chunk_index": i,
            "total_chunks": len(chunks),
        })
        payload = {
            "document": chunk,
            "metadata": metadata,
        }
        points.append(PointStruct(id=point_id, vector={settings.vector_name: vector.tolist()}, payload=payload))
        print(f"Prepared Point ID: {point_id} with payload keys: {list(payload.keys())}")
    return points


async def upsert_points(client: AsyncQdrantClient, collection_name: str, points: list[PointStruct]) -> None:
    print(f"Upserting {len(points)} points into collection '{collection_name}'")
    await client.upsert(collection_name=collection_name, points=points)
    print("Upsert completed.")
