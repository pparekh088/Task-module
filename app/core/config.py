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

    azure_blob_connection_string: Optional[str] = Field(
        default=None, alias="AZURE_BLOB_CONNECTION_STRING"
    )
    azure_blob_container: Optional[str] = Field(default=None, alias="AZURE_BLOB_CONTAINER")
    azure_blob_sas_token: Optional[str] = Field(default=None, alias="AZURE_BLOB_SAS_TOKEN")
    azure_blob_account_key: Optional[str] = Field(default=None, alias="AZURE_BLOB_ACCOUNT_KEY")

    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")
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
