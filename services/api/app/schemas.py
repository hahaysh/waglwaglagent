from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openrouter", "gemini"]
    label: str = Field(min_length=1, max_length=80)
    api_key: SecretStr = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_./:\-]+$")
    upstreams: list[str] = Field(default_factory=list, max_length=10)
    approved: bool = False
    priority: int = Field(default=0, ge=0, le=100)
    quota_group: str = Field(default="account", min_length=1, max_length=100)

    @field_validator("api_key")
    @classmethod
    def valid_api_key(cls, value: SecretStr):
        if any(character.isspace() for character in value.get_secret_value()):
            raise ValueError("Key must not contain whitespace")
        return value


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    priority: int = Field(default=0, ge=0, le=100)
    upstreams: list[str] = Field(default_factory=list, max_length=10)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=36)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9\-]{8,64}$")

    @field_validator("prompt")
    @classmethod
    def meaningful_prompt(cls, value: str):
        if not value.strip():
            raise ValueError("Prompt must not be blank")
        return value
