"""config/settings.py"""
from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    app_name: str = "PresalesAI Platform"
    app_version: str = "2.0.0"
    debug: bool = False
    secret_key: str = "change-me-in-production-minimum-32-chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    database_url: str = "sqlite+aiosqlite:///./presales_platform.db"
    database_echo: bool = False
    gemini_api_key: str = ""
    gemini_pro_model: str = "gemini-1.5-pro"
    gemini_flash_model: str = "gemini-1.5-flash"
    whisper_model: str = "base"
    upload_dir: str = "./uploads"
    proposal_dir: str = "./proposals"
    max_upload_size_mb: int = 50
    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_proposals: str = "proposals"
    chroma_collection_conversations: str = "conversations"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    lead_score_high_threshold: int = 75
    lead_score_medium_threshold: int = 50

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
