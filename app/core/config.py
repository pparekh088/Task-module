from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "task-planner-service"

    azure_openai_endpoint: Optional[str] = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: Optional[str] = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    azure_openai_api_version: str = Field(default="2024-10-01-preview", alias="AZURE_OPENAI_API_VERSION")
    azure_openai_gpt52_deployment: Optional[str] = Field(
        default=None, alias="AZURE_OPENAI_GPT52_DEPLOYMENT"
    )
    azure_openai_vision_deployment: Optional[str] = Field(
        default=None, alias="AZURE_OPENAI_VISION_DEPLOYMENT"
    )

    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")
    redis_file_cache_enabled: bool = Field(default=True, alias="REDIS_FILE_CACHE_ENABLED")
    redis_file_cache_ttl_seconds: int = Field(
        default=3600, alias="REDIS_FILE_CACHE_TTL_SECONDS"
    )
    redis_file_cache_max_chars: int = Field(
        default=12000, alias="REDIS_FILE_CACHE_MAX_CHARS"
    )
    sql_database_url: str = Field(
        default="sqlite+aiosqlite:///./planner.db", alias="SQL_DATABASE_URL"
    )

    max_file_context_chars: int = Field(default=6000, alias="MAX_FILE_CONTEXT_CHARS")
    max_file_rows: int = Field(default=200, alias="MAX_FILE_ROWS")
    max_ocr_pages: int = Field(default=10, alias="MAX_OCR_PAGES")
    min_pdf_text_chars: int = Field(default=50, alias="MIN_PDF_TEXT_CHARS")
    planning_max_output_tokens: int = Field(
        default=2500, alias="PLANNING_MAX_OUTPUT_TOKENS"
    )
    planning_max_tokens: Optional[int] = Field(
        default=None, alias="PLANNING_MAX_TOKENS"
    )
    planning_temperature: Optional[float] = Field(default=None, alias="PLANNING_TEMPERATURE")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
