import base64
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WAGL_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: str = "local"
    database_url: str = "sqlite:///./.local/wagl.db"
    redis_url: str = ""
    internal_secret: str
    encryption_key: str
    gemini_reviews: dict[str, dict] = {}
    public_url: str = "http://localhost:3000"
    copilot_client_id: str = ""
    copilot_client_secret: str = ""

    @model_validator(mode="after")
    def validate_security(self):
        if len(self.internal_secret) < 32:
            raise ValueError("Internal secret must contain at least 32 characters")
        if len(base64.b64decode(self.encryption_key, validate=True)) != 32:
            raise ValueError("Encryption key must be a base64-encoded 32-byte key")
        if self.environment not in {"local", "production"}:
            raise ValueError("Environment must be local or production")
        if self.environment == "production":
            if not self.database_url.startswith("postgresql+psycopg://") or not self.redis_url:
                raise ValueError("Production requires PostgreSQL and Redis")
            if self.gemini_reviews:
                raise ValueError(
                    "Gemini billing tier cannot be continuously verified in production"
                )
        from urllib.parse import urlsplit

        origin = urlsplit(self.public_url)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
            or (
                origin.scheme == "http"
                and (self.environment == "production" or origin.hostname not in {
                    "localhost", "127.0.0.1", "::1",
                })
            )
        ):
            raise ValueError("Public URL must be an HTTPS origin or local loopback origin")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
