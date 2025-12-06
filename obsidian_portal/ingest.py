import abc
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

from config import VECTOR_NAME

DocType = Literal["WikiPage", "Post", "Character"]


class Document(abc.ABC, BaseModel):
    id: str
    type: DocType
    source_url: str
    tags: list[str]
    gm_only: bool = Field(validation_alias="is_game_master_only")
    created_at: str
    updated_at: str

    @property
    @abc.abstractmethod
    def content(self) -> str:
        pass

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source_url": self.source_url,
            "tags": self.tags,
            "gm_only": self.gm_only,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Page(Document):
    title: str = Field(validation_alias="name")
    body: str
    source_url: str = Field(validation_alias="wiki_page_url")

    @property
    def content(self) -> str:
        return self.body

    @property
    def metadata(self) -> dict[str, Any]:
        metadata = super().metadata.copy()
        metadata.update({
            "title": self.title,
        })
        return metadata


class Character(Document):
    name: str
    description: str
    bio: str
    is_player_character: bool
    source_url: str = Field(validation_alias="character_url")
    type: DocType = "Character"

    @property
    def content(self) -> str:
        return f"{self.name}\n\n{self.description}\n\n{self.bio}"

    @property
    def metadata(self) -> dict[str, Any]:
        metadata = super().metadata.copy()
        metadata.update({
            "name": self.name,
            "is_player_character": self.is_player_character,
        })
        return metadata


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


def prepare_document_points(doc: Document, embed_model: SentenceTransformer) -> list[PointStruct]:
    print(f"Ingesting document ID: {doc.id}, Type: {doc.type}")
    chunks = chunk_text(doc.content)
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i + 1}/{len(chunks)} (Length: {len(chunk)} chars)")

    vectors = embed_model.encode(chunks).tolist()
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
            "metadata": doc.metadata,
        }
        points.append(PointStruct(id=point_id, vector={VECTOR_NAME: vector}, payload=payload))
        print(f"Prepared Point ID: {point_id} with payload keys: {list(payload.keys())}")
    return points


async def upsert_points(client: AsyncQdrantClient, collection_name: str, points: list[PointStruct]) -> None:
    print(f"Upserting {len(points)} points into collection '{collection_name}'")
    await client.upsert(collection_name=collection_name, points=points)
    print("Upsert completed.")
