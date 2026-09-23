from typing import Literal
from urllib.parse import urlsplit

from httpx2 import URL, InvalidURL
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import WORKSPACE_ROOT


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WORKSPACE_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )
    model_provider: Literal["mock", "cloud"] = "mock"
    model_base_url: str = ""
    model_id: str = ""
    model_api_key: SecretStr = SecretStr("")
    model_allowed_ids: list[str] = Field(default_factory=list)
    model_connect_timeout_seconds: float = Field(default=10, gt=0, le=120)
    model_read_timeout_seconds: float = Field(default=30, gt=0, le=300)
    model_max_output_tokens: int = Field(default=512, ge=1, le=32768)

    @model_validator(mode="after")
    def validate_cloud(self):
        if self.model_provider == "mock":
            return self
        try:
            urlsplit(self.model_base_url)  # Reject malformed bracket syntax too.
            parsed = URL(self.model_base_url)
            _ = parsed.port
        except (ValueError, InvalidURL):
            raise ValueError("MODEL_BASE_URL is invalid") from None
        if (
            not parsed.host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.scheme not in ("https", "http")
            or (parsed.scheme == "http" and parsed.host not in ("127.0.0.1", "localhost", "::1"))
        ):
            raise ValueError(
                "MODEL_BASE_URL must be HTTPS (HTTP only for loopback), without secrets"
            )
        if (
            not self.model_id.strip()
            or self.model_id not in self.model_allowed_ids
            or any(ord(char) < 32 for char in self.model_id)
        ):
            raise ValueError("MODEL_ID must be in MODEL_ALLOWED_IDS")
        key = self.model_api_key.get_secret_value()
        if not key.strip() or any(ord(char) < 32 or ord(char) > 126 for char in key):
            raise ValueError("MODEL_API_KEY must contain a nonempty ASCII credential")
        return self
