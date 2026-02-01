from functools import lru_cache
from typing import Optional
from urllib.parse import quote_plus

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
    redis_password_cache_ttl_seconds: int = Field(
        default=300, alias="REDIS_PASSWORD_CACHE_TTL_SECONDS"
    )
    azure_key_vault_url: Optional[str] = Field(default=None, alias="AZURE_KEY_VAULT_URL")
    azure_redis_password_secret_name: Optional[str] = Field(
        default=None, alias="AZURE_REDIS_PASSWORD_SECRET_NAME"
    )
    azure_redis_host: Optional[str] = Field(default=None, alias="AZURE_REDIS_HOST")
    azure_redis_port: int = Field(default=6380, alias="AZURE_REDIS_PORT")
    azure_redis_ssl: bool = Field(default=True, alias="AZURE_REDIS_SSL")
    sql_database_url: Optional[str] = Field(default=None, alias="SQL_DATABASE_URL")
    azure_sql_server: Optional[str] = Field(default=None, alias="AZURE_SQL_SERVER")
    azure_sql_database: Optional[str] = Field(default=None, alias="AZURE_SQL_DATABASE")
    azure_sql_user: Optional[str] = Field(default=None, alias="AZURE_SQL_USER")
    azure_sql_password: Optional[str] = Field(default=None, alias="AZURE_SQL_PASSWORD")
    azure_sql_odbc_driver: str = Field(
        default="ODBC Driver 18 for SQL Server", alias="AZURE_SQL_ODBC_DRIVER"
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

    def resolve_database_url(self) -> str:
        if self.sql_database_url:
            return self.sql_database_url
        if (
            self.azure_sql_server
            and self.azure_sql_database
            and self.azure_sql_user
            and self.azure_sql_password
        ):
            odbc_params = (
                f"Driver={{{self.azure_sql_odbc_driver}}};"
                f"Server=tcp:{self.azure_sql_server},1433;"
                f"Database={self.azure_sql_database};"
                f"Uid={self.azure_sql_user};"
                f"Pwd={self.azure_sql_password};"
                "Encrypt=yes;"
                "TrustServerCertificate=no;"
                "Connection Timeout=30;"
            )
            encoded = quote_plus(odbc_params)
            return f"mssql+aioodbc:///?odbc_connect={encoded}"
        raise ValueError("SQL database configuration is missing.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
