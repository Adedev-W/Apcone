from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "apcone"
    database_url: str = Field(
        default="postgresql+psycopg://apcone:apcone_password@localhost:5433/apcone"
    )
    redis_url: str = Field(default="redis://localhost:6380/0")
    upload_storage_dir: str = Field(default="storage/uploads")
    pdf_queue_name: str = Field(default="pdf_ingest")
    pdf_text_threshold: int = Field(default=80, ge=0)
    pdf_image_threshold: int = Field(default=1, ge=0)
    pdf_scanner_grpc_url: str = Field(default="127.0.0.1:50051")
    pdf_scanner_language: str = Field(default="eng", min_length=2)
    pdf_scanner_max_mb: int = Field(default=100, ge=1)
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_http_port: int = Field(default=6333)
    qdrant_grpc_port: int = Field(default=6334)
    qdrant_collection: str = Field(default="rag_chunks")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    chunk_size: int = Field(default=1000, ge=200)
    chunk_overlap: int = Field(default=150, ge=0)
    search_top_k: int = Field(default=5, ge=1, le=50)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
