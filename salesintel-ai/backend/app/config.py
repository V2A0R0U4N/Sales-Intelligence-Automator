"""
Pydantic Settings — Centralized configuration loaded from environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from .env file or environment."""

    # --- App ---
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    backend_url: str = Field(default="http://localhost:8000")
    frontend_url: str = Field(default="http://localhost:3000")

    # --- Database ---
    database_url: str = Field(default="postgresql+asyncpg://salesintel:salesintel@db:5432/salesintel")
    sync_database_url: str = Field(default="postgresql://salesintel:salesintel@db:5432/salesintel")

    # --- Redis ---
    redis_url: str = Field(default="redis://redis:6379/0")

    # --- Qdrant ---
    qdrant_url: str = Field(default="http://qdrant:6333")
    qdrant_api_key: str = Field(default="")

    # --- Elasticsearch ---
    elasticsearch_url: str = Field(default="http://elasticsearch:9200")

    # --- LLM / Groq ---
    groq_api_key: str = Field(default="")
    groq_chat_model: str = Field(default="llama3-70b-8192")

    # --- Auth ---
    jwt_secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30)

    # --- External APIs ---
    google_custom_search_api_key: str = Field(default="")
    google_custom_search_engine_id: str = Field(default="")
    apollo_api_key: str = Field(default="")
    sendgrid_api_key: str = Field(default="")
    hubspot_access_token: str = Field(default="")
    bright_data_proxy_url: str = Field(default="")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
