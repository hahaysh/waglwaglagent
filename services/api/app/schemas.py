import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.attachments import MAX_ATTACHMENT_BYTES, AttachmentInput


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openrouter", "gemini", "openai", "anthropic"]
    label: str = Field(min_length=1, max_length=80)
    api_key: SecretStr = Field(min_length=8, max_length=500)
    model: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_./:\-]+$"
    )
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
    prompt: str = Field(default="", max_length=8000)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=3)
    conversation_id: str | None = Field(default=None, max_length=36)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9\-]{8,64}$")
    credential_id: str | None = Field(default=None, pattern=r"^[a-f0-9\-]{36}$")

    @model_validator(mode="after")
    def meaningful_prompt(self):
        if not self.prompt.strip() and not self.attachments:
            raise ValueError("Prompt must not be blank")
        total_bytes = sum(len(base64.b64decode(file.data)) for file in self.attachments)
        if total_bytes > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment_too_large")
        return self
