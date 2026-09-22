import unicodedata
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr

Role = Literal["user", "agent", "admin"]


def normalize_username(value: str) -> str:
    return (
        unicodedata.normalize("NFKC", value).strip().casefold() if isinstance(value, str) else value
    )


Username = Annotated[str, BeforeValidator(normalize_username), Field(min_length=3, max_length=50)]
DisplayName = Annotated[
    str,
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
    Field(min_length=1, max_length=100),
]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Username
    password: SecretStr = Field(min_length=12, max_length=128)


class RegisterInput(LoginInput):
    display_name: DisplayName


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime


class LoginResult(BaseModel):
    user: UserSummary
    csrf_token: str


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: UUID
    role: Role
