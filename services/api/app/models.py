import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Request
from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import TypeDecorator

from app.config import get_settings
from app.encryption import seal, unseal


def identifier() -> str:
    return str(uuid4())


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, context: str):
        super().__init__()
        self.context = context

    def process_bind_param(self, value, dialect):
        return None if value is None else seal(value, self.context)

    def process_result_value(self, value, dialect):
        return None if value is None else unseal(value, self.context)


class EncryptedAttachments(TypeDecorator):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return {"encrypted": seal(json.dumps(value), "messages.attachments")}

    def process_result_value(self, value, dialect):
        if not isinstance(value, dict) or set(value) != {"encrypted"}:
            raise ValueError("Unencrypted attachments; run database migrations before starting")
        return json.loads(unseal(value["encrypted"], "messages.attachments"))


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        Index(
            "uq_provider_account", "owner_id", "provider", "provider_subject",
            unique=True, mssql_where=text("provider_subject IS NOT NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(EncryptedText("credentials.label"))
    encrypted_key: Mapped[str] = mapped_column("encrypted_secret", Text)
    secret_format: Mapped[str] = mapped_column(String(30), default="api_key_v1")
    encryption_key_version: Mapped[int] = mapped_column(Integer, default=1)
    auth_type: Mapped[str] = mapped_column(String(20), default="api_key")
    auth_status: Mapped[str] = mapped_column(String(30), default="authenticated")
    provider_subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    usage_policy: Mapped[str] = mapped_column(String(30), default="free_only")
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="unverified")
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    upstreams: Mapped[list] = mapped_column(JSON, default=list)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    consent_version: Mapped[str] = mapped_column(String(36), default=identifier)
    quota_group: Mapped[str] = mapped_column(String(100), default="account")
    quota_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


class OAuthAttempt(Base):
    __tablename__ = "oauth_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    binding_hash: Mapped[str] = mapped_column(String(64))
    encrypted_verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[str] = mapped_column(String(40))
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(EncryptedText("conversations.title"))
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(EncryptedText("messages.content"))
    attachments: Mapped[list] = mapped_column(EncryptedAttachments(), default=list)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="complete")
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="running")
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(200))
    upstreams: Mapped[list] = mapped_column(JSON, default=list)
    consent_version: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), default="started")
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


def make_engine(url: str):
    options = {}
    if url.startswith("mssql+"):
        options = {
            "pool_pre_ping": True, "pool_size": 3, "max_overflow": 2,
            "deprecate_large_types": True,
        }
    engine = create_engine(
        url, connect_args={"check_same_thread": False} if url.startswith("sqlite:") else {},
        **options,
    )
    if url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def initialize_database():
    settings = get_settings()
    if settings.database_url.startswith("sqlite:"):
        Path(".local").mkdir(exist_ok=True)
    engine = make_engine(settings.database_url)
    if settings.environment == "local":
        Base.metadata.create_all(engine)
    return engine


def session_for(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
