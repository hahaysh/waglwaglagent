import base64
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WAGL_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: str = "local"
    database_url: str = Field(default="sqlite:///./.local/wagl.db", repr=False)
    redis_url: str = Field(default="", repr=False)
    internal_secret: str = Field(repr=False)
    encryption_key: str = Field(repr=False)
    key_vault_url: str = ""
    app_config_endpoint: str = ""
    app_config_label: str = ""
    azure_tenant_id: str = ""
    managed_identity_client_id: str = ""
    gemini_reviews: dict[str, dict] = {}
    public_url: str = "http://localhost:3000"
    copilot_client_id: str = ""
    copilot_client_secret: str = Field(default="", repr=False)

    @model_validator(mode="before")
    @classmethod
    def resolve_vault_references(cls, values):
        from app.vault import read_reference, validate_vault_url, vault_client

        values = dict(values)
        if values.get("app_config_endpoint"):
            from app.central_config import load_configuration

            central = load_configuration(
                values["app_config_endpoint"], values.get("app_config_label", ""),
                values.get("environment", "local"), values.get("azure_tenant_id", ""),
                values.get("managed_identity_client_id", ""),
            )
            for key, value in central.items():
                field = key.removeprefix("WAGL_").lower()
                if field in cls.model_fields and field not in {
                    "app_config_endpoint", "app_config_label", "environment",
                    "azure_tenant_id", "managed_identity_client_id",
                }:
                    values[field] = value
        url = values.get("key_vault_url", "")
        environment = values.get("environment", "local")
        if environment == "production" and not url:
            raise ValueError("Production requires Azure Key Vault")
        if environment == "production" and not values.get("app_config_endpoint"):
            raise ValueError("Production requires Azure App Configuration")
        client = None
        if url:
            validate_vault_url(url)
            client = vault_client(
                url, environment, values.get("azure_tenant_id", ""),
                values.get("managed_identity_client_id", ""),
            )
        for field in (
            "internal_secret", "encryption_key", "copilot_client_id", "copilot_client_secret",
            "database_url", "redis_url",
        ):
            value = values.get(field, "")
            if isinstance(value, str) and value.startswith("kv://"):
                if client is None:
                    raise ValueError("Key Vault references require WAGL_KEY_VAULT_URL")
                values[field] = read_reference(client, value)
            elif url and value and field in {
                "internal_secret", "encryption_key", "copilot_client_secret",
            }:
                raise ValueError("Sensitive settings must use Key Vault references")
            elif url and field in {"database_url", "redis_url"} and value:
                from urllib.parse import urlsplit

                if urlsplit(value).password:
                    raise ValueError("Connection passwords must use Key Vault references")
        return values

    @model_validator(mode="after")
    def validate_security(self):
        if len(self.internal_secret) < 32:
            raise ValueError("Internal secret must contain at least 32 characters")
        if len(base64.b64decode(self.encryption_key, validate=True)) != 32:
            raise ValueError("Encryption key must be a base64-encoded 32-byte key")
        if self.environment not in {"local", "production"}:
            raise ValueError("Environment must be local or production")
        if self.environment == "production":
            if not self.redis_url:
                raise ValueError("Production requires Redis")
            if self.database_url.startswith("mssql+mssqlpython://"):
                from sqlalchemy.engine import make_url

                database = make_url(self.database_url)
                if (
                    not database.host
                    or not database.host.endswith(".database.windows.net")
                    or database.username not in {None, ""}
                    or database.password is not None
                    or not database.database
                    or database.port not in {None, 1433}
                    or dict(database.query) != {
                        "authentication": "ActiveDirectoryMSI",
                        "encrypt": "yes",
                        "trustservercertificate": "no",
                    }
                ):
                    raise ValueError(
                        "Azure SQL requires certificate-verified Managed Identity auth"
                    )
            elif not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires Azure SQL or PostgreSQL")
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
