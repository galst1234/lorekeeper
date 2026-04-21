import abc
from typing import Any, Literal

from pydantic import BaseModel, Field

DocType = Literal["WikiPage", "Post", "Character"]


class Document(abc.ABC, BaseModel):
    id: str
    slug: str
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
            "slug": self.slug,
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
    description: str | None = None
    bio: str | None = None
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


class PageSummary(BaseModel):
    """Lightweight page representation for catalog/discovery — no body content."""

    id: str
    slug: str
    title: str
    tags: list[str]
    gm_only: bool


class CharacterRequest(BaseModel):
    name: str
    description: str | None = None
    bio: str | None = None
    tagline: str | None = None
    tags: list[str] = Field(default_factory=list)


QuestStatus = Literal["open", "completed", "failed"]
QuestType = Literal["Main Quest", "Side Quest"]


class Quest(BaseModel):
    title: str
    content: str
    status: QuestStatus
    phase: str
    quest_type: QuestType | None = None
