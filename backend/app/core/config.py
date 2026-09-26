from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WORKSPACE_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    session_secret: SecretStr = Field(validation_alias="SESSION_SECRET")
    upload_dir: Path = Field(validation_alias="UPLOAD_DIR")

    embedding_tokenizer_path: str = Field(default="", validation_alias="EMBEDDING_TOKENIZER_PATH")
    embedding_model_path: str = Field(default="", validation_alias="EMBEDDING_MODEL_PATH")
    retrieval_threshold: float = Field(
        default=0.65, ge=-1, le=1, validation_alias="RETRIEVAL_THRESHOLD"
    )
    ingestion_parse_timeout: int = Field(
        default=60, ge=1, le=300, validation_alias="INGESTION_PARSE_TIMEOUT"
    )

    chat_requests_per_minute: int = Field(
        default=10, ge=1, validation_alias="CHAT_REQUESTS_PER_MINUTE"
    )
    chat_requests_per_day: int = Field(
        default=60, ge=1, validation_alias="CHAT_REQUESTS_PER_DAY"
    )
    chat_global_concurrency: int = Field(
        default=2, ge=1, validation_alias="CHAT_GLOBAL_CONCURRENCY"
    )

    public_origin: str | None = Field(default=None, validation_alias="PUBLIC_ORIGIN")

    login_account_limit: int = Field(default=5, ge=1, validation_alias="LOGIN_ACCOUNT_LIMIT")
    login_ip_limit: int = Field(default=30, ge=1, validation_alias="LOGIN_IP_LIMIT")
    login_window_seconds: int = Field(default=300, ge=1, validation_alias="LOGIN_WINDOW_SECONDS")
    login_max_entries: int = Field(default=10000, ge=2, validation_alias="LOGIN_MAX_ENTRIES")

    @model_validator(mode="after")
    def validate_auth_deployment(self):
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                raise ValueError("PUBLIC_ORIGIN must contain only an http(s) origin")
            _ = parsed.port
        if self.app_env == "production":
            if not self.public_origin or urlsplit(self.public_origin).scheme != "https":
                raise ValueError("production requires an HTTPS PUBLIC_ORIGIN")
            if len(self.session_secret.get_secret_value()) < 32:
                raise ValueError("production SESSION_SECRET must have at least 32 characters")
        return self

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+psycopg" and url.host and url.database
        except (ArgumentError, ValueError):
            valid = False
        if not valid:
            raise ValueError("must be a postgresql+psycopg URL with a host and database")
        return value

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("upload_dir", mode="before")
    @classmethod
    def resolve_upload_dir(cls, value: str | Path) -> Path:
        if not str(value).strip():
            raise ValueError("must not be empty")
        path = Path(value)
        return path if path.is_absolute() else WORKSPACE_ROOT / path
