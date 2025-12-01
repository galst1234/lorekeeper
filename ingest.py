import dataclasses
from typing import Literal
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

from config import VECTOR_NAME

DocType = Literal["WikiPage", "Post", "Character"]


@dataclasses.dataclass
class Document:
    id: str
    type: DocType
    title: str
    content: str
    source_url: str
    tags: list[str]
    gm_only: bool
    created_at: str
    updated_at: str


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
                if overlap_chars > 0:
                    last_chunk = current[-overlap_chars:]
                else:
                    last_chunk = ""
            # Start new chunk with overlap
            current = (last_chunk + "\n" + p).strip() if last_chunk else p

    if current:
        chunks.append(current)

    return chunks


def prepare_document_points(doc: Document, embed_model: SentenceTransformer) -> list[PointStruct]:
    print(f"Ingesting document ID: {doc.id}, Type: {doc.type}, Title: {doc.title}")
    chunks = chunk_text(doc.content)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i + 1}/{len(chunks)} (Length: {len(chunk)} chars):\n{chunk}\n")

    vectors = embed_model.encode(chunks).tolist()
    points = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        point_id = str(uuid4())
        payload = {
            "document": chunk,
            "metadata": {
                "doc_id": doc.id,
                "type": doc.type,
                "title": doc.title,
                "source_url": doc.source_url,
                "tags": doc.tags,
                "gm_only": doc.gm_only,
                "created_at": doc.created_at,
                "updated_at": doc.updated_at,
                "chunk_index": i,
            }
        }
        points.append(PointStruct(id=point_id, vector={VECTOR_NAME: vector}, payload=payload))
        print(f"Prepared Point ID: {point_id} with payload keys: {list(payload.keys())}")
    return points


def upsert_points(client: QdrantClient, collection_name: str, points: list[PointStruct]):
    print(f"Upserting {len(points)} points into collection '{collection_name}'")
    client.upsert(collection_name=collection_name, points=points)
    print("Upsert completed.")
