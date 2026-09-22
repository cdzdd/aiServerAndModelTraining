from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
