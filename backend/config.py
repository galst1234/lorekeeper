from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Obsidian Portal OAuth1
    consumer_key: str
    consumer_secret: str
    request_token_url: str
    access_token_url: str
    authorize_url: str
    campaign_id: str
    quest_log_page_id: str
    calendar_page_id: str

    # Qdrant
    qdrant_url: str
    collection_name: str

    # Ollama
    ollama_url: str
    ollama_model: str = "llama3.1:8b-instruct-q4_K_M"

    # OpenRouter
    openrouter_url: str
    openrouter_api_key: str
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # Groq
    groq_api_url: str
    groq_api_key: str
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-5-mini-2025-08-07"

    # Misc
    data_dir: Path = Field(default=Path("."))
    vector_name: str = "fast-bge-base-en-v1.5"


settings = Settings()  # type: ignore[call-arg]
