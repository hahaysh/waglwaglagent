import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.attachments import MAX_CONTEXT_IMAGE_BYTES, context_size, prepare_messages
from app.connections import revoke_copilot, router, usage_state, verify_copilot
from app.copilot_provider import UPSTREAM, CopilotProvider
from app.models import (
    Attempt,
    Conversation,
    Credential,
    Message,
    OAuthAttempt,
    Run,
    identifier,
    initialize_database,
    session_for,
    timestamp,
)
from app.providers import ProviderError, Providers
from app.quotas import Limits
from app.routing import Candidate, Failure, eligible_candidates, may_fallback
from app.schemas import ChatInput, CredentialInput, PolicyInput
from app.security import (
    authenticated_owner,
    decrypt_key,
    decrypt_oauth,
    delete_key,
    encrypt_key,
    key_fingerprint,
)
from app.vault import SecretMissingError, SecretStoreError

Owner = Annotated[str, Depends(authenticated_owner)]
Database = Annotated[Session, Depends(session_for)]
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    from app.config import get_settings

    application.state.engine = initialize_database()
    application.state.providers = Providers()
    application.state.copilot = CopilotProvider()
    application.state.limits = Limits(get_settings().redis_url)
    application.state.active = {}
    application.state.connection_lock = asyncio.Lock()
    yield
    for task in list(application.state.active.values()):
        task.cancel()
    await application.state.providers.close()
    await application.state.limits.close()
    application.state.engine.dispose()


app = FastAPI(title="waglwaglagent policy API", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def invalid_input(_request, _error):
    for error in _error.errors():
        reason = str(error.get("ctx", {}).get("error", ""))
        if reason in {"attachment_invalid", "attachment_too_large", "attachment_unsupported"}:
            return JSONResponse({"detail": reason}, status_code=422)
    return JSONResponse({"detail": "Invalid input"}, status_code=422)


@app.exception_handler(ProviderError)
async def provider_error(_request, error: ProviderError):
    status = 422 if error.failure in {Failure.INVALID, Failure.AUTH} else 503
    return JSONResponse({"detail": error.code}, status_code=status)


@app.exception_handler(SecretStoreError)
async def secret_store_error(_request, _error):
    return JSONResponse({"detail": "secret_store_unavailable"}, status_code=503)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request):
    def check_database():
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    try:
        await asyncio.to_thread(check_database)
        redis = request.app.state.limits.redis
        if redis is not None and not await redis.ping():
            raise RedisError("Redis readiness check failed")
    except (SQLAlchemyError, RedisError) as error:
        logger.warning("API readiness failed (%s)", type(error).__name__)
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}


def own_credential(database: Session, owner: str, credential_id: str) -> Credential:
    credential = database.scalar(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.owner_id == owner,
        )
    )
    if not credential:
        raise HTTPException(404, "Credential not found")
    return credential


def own_conversation(database: Session, owner: str, conversation_id: str) -> Conversation:
    conversation = database.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == owner,
        )
    )
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


def quota_scope(credential: Credential) -> str:
    if credential.provider == "copilot":
        if not credential.provider_subject:
            raise ProviderError(Failure.AUTH, "reauth_required")
        return f"copilot:{credential.provider_subject}"
    return f"{credential.provider}:{credential.quota_group}"


def public_credential(credential: Credential) -> dict:
    result = {
        field: getattr(credential, field)
        for field in (
            "id",
            "provider",
            "label",
            "model",
            "upstreams",
            "approved",
            "priority",
            "status",
            "consent_version",
            "quota_snapshot",
            "checked_at",
            "created_at",
            "auth_type",
            "auth_status",
            "expires_at",
            "usage_policy",
        )
    }
    result["usage_state"] = usage_state(credential)
    return result


@app.get("/catalog")
async def catalog(request: Request, owner: Owner):
    await request.app.state.limits.rate_limit(owner, "catalog", 30)
    return await request.app.state.providers.free_models()


@app.get("/endpoints")
async def endpoints(request: Request, owner: Owner, model: str):
    await request.app.state.limits.rate_limit(owner, "catalog", 30)
    if len(model) > 200:
        raise HTTPException(422, "Invalid model")
    return {"endpoints": await request.app.state.providers.endpoints(model)}


@app.get("/credentials")
async def credentials(database: Database, owner: Owner):
    return [
        public_credential(credential)
        for credential in database.scalars(
            select(Credential).where(Credential.owner_id == owner).order_by(Credential.priority)
        )
    ]


@app.post("/credentials", status_code=201)
async def create_credential(
    body: CredentialInput, request: Request, database: Database, owner: Owner
):
    async with request.app.state.connection_lock:
        return await save_api_key(body, request, database, owner)


async def save_api_key(
    body: CredentialInput, request: Request, database: Session, owner: str,
):
    await request.app.state.limits.rate_limit(owner, "credential", 10)
    count = database.scalar(
        select(func.count())
        .select_from(Credential)
        .where(
            Credential.owner_id == owner,
        )
    )
    if count >= 5:
        raise HTTPException(409, "Credential limit reached")
    if body.provider == "openrouter" and not body.model:
        raise HTTPException(422, "Invalid input")
    if body.provider == "openrouter":
        upstreams = await request.app.state.providers.endpoints(body.model)
        allowed = {endpoint["id"] for endpoint in upstreams}
        if set(body.upstreams) - allowed or (body.approved and not body.upstreams):
            raise HTTPException(422, "Approved inference provider required")
    raw_key = body.api_key.get_secret_value()
    fingerprint = key_fingerprint(raw_key)
    if database.scalar(select(Credential.id).where(
        Credential.owner_id == owner, Credential.provider == body.provider,
        Credential.fingerprint == fingerprint,
    )):
        raise HTTPException(409, "duplicate_connection")
    snapshot = await request.app.state.providers.validate(body.provider, raw_key)
    credential_id = identifier()
    credential = Credential(
        id=credential_id,
        owner_id=owner,
        provider=body.provider,
        label=body.label,
        encrypted_key=await asyncio.to_thread(encrypt_key, raw_key, owner, credential_id),
        fingerprint=fingerprint,
        model=body.model,
        upstreams=list(dict.fromkeys(body.upstreams)),
        approved=False,
        priority=body.priority,
        quota_group=body.quota_group,
        quota_snapshot=snapshot,
        status=snapshot["status"],
        checked_at=timestamp(),
    )
    database.add(credential)
    database.commit()
    return public_credential(credential)


@app.patch("/credentials/{credential_id}")
async def update_policy(
    credential_id: str,
    body: PolicyInput,
    request: Request,
    database: Database,
    owner: Owner,
):
    credential = own_credential(database, owner, credential_id)
    if credential.provider == "copilot" and body.approved and body.upstreams != [UPSTREAM]:
        raise HTTPException(422, "Approved inference provider required")
    if credential.provider == "openrouter" and body.approved:
        allowed = {
            endpoint["id"]
            for endpoint in await request.app.state.providers.endpoints(
                credential.model,
            )
        }
        if set(body.upstreams) - allowed or (body.approved and not body.upstreams):
            raise HTTPException(422, "Approved inference provider required")
    credential.approved = body.approved
    credential.priority = body.priority
    credential.upstreams = list(dict.fromkeys(body.upstreams))
    credential.consent_version = identifier()
    database.commit()
    if not body.approved and owner in request.app.state.active:
        request.app.state.active[owner].cancel()
    return public_credential(credential)


@app.post("/credentials/{credential_id}/verify")
async def verify_credential(credential_id: str, request: Request, database: Database, owner: Owner):
    async with request.app.state.connection_lock:
        return await verify_connection(credential_id, request, database, owner)


async def verify_connection(
    credential_id: str, request: Request, database: Session, owner: str,
):
    await request.app.state.limits.rate_limit(owner, "credential", 10)
    credential = own_credential(database, owner, credential_id)
    try:
        if credential.auth_type == "oauth":
            snapshot = await verify_copilot(
                request.app.state.providers.client, credential, database,
            )
            if credential.auth_status == "authenticated":
                tokens = await asyncio.to_thread(
                    decrypt_oauth, credential.encrypted_key, owner, credential.id,
                )
                snapshot = await request.app.state.copilot.verify(tokens["access_token"])
                credential.model = "auto"
                if snapshot["status"] == "invalid":
                    credential.auth_status = "reauth_required"
        else:
            snapshot = await request.app.state.providers.validate(
                credential.provider,
                await asyncio.to_thread(
                    decrypt_key, credential.encrypted_key, owner, credential.id,
                ),
            )
            credential.auth_status = "authenticated"
        credential.status = snapshot["status"]
        credential.quota_snapshot = snapshot
    except ProviderError as error:
        if error.failure == Failure.AUTH:
            credential.status = "invalid"
            credential.auth_status = "reauth_required"
        elif credential.provider == "copilot":
            credential.status = "unverified"
            credential.quota_snapshot = {
                "status": "unverified", "reason": error.code, "source": "copilot_sdk",
            }
        database.commit()
        raise
    credential.checked_at = timestamp()
    database.commit()
    return public_credential(credential)


@app.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: str, request: Request, database: Database, owner: Owner):
    async with request.app.state.connection_lock:
        return await disconnect(credential_id, request, database, owner)


async def disconnect(
    credential_id: str, request: Request, database: Session, owner: str,
):
    credential = own_credential(database, owner, credential_id)
    tokens, missing_oauth = None, False
    if credential.auth_type == "oauth":
        try:
            tokens = await asyncio.to_thread(
                decrypt_oauth, credential.encrypted_key, owner, credential.id,
            )
        except SecretMissingError:
            missing_oauth = True
    if owner in request.app.state.active:
        request.app.state.active[owner].cancel()
    await asyncio.to_thread(
        delete_key, credential.encrypted_key, owner,
        f"{credential.id}:oauth_v1" if credential.auth_type == "oauth" else credential.id,
    )
    database.execute(update(OAuthAttempt).where(
        OAuthAttempt.owner_id == owner, OAuthAttempt.provider == credential.provider,
    ).values(status="cancelled", encrypted_verifier=None))
    database.delete(credential)
    database.commit()
    if missing_oauth or (
        tokens and not await revoke_copilot(request.app.state.providers.client, tokens)
    ):
        return JSONResponse(
            {"detail": "local_disconnect_only"}, status_code=200,
        )


@app.get("/conversations")
async def conversations(database: Database, owner: Owner):
    return [
        {"id": conversation.id, "title": conversation.title, "created_at": conversation.created_at}
        for conversation in database.scalars(
            select(Conversation)
            .where(
                Conversation.owner_id == owner,
            )
            .order_by(Conversation.created_at.desc())
            .limit(100)
        )
    ]


@app.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str, database: Database, owner: Owner):
    conversation = own_conversation(database, owner, conversation_id)
    messages = database.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
        )
        .order_by(Message.created_at, Message.id)
    )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "messages": [
            {
                field: getattr(message, field)
                for field in (
                    "id",
                    "role",
                    "content",
                    "attachments",
                    "provider",
                    "model",
                    "status",
                    "created_at",
                )
            }
            for message in messages
        ],
    }


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, request: Request, database: Database, owner: Owner
):
    conversation = own_conversation(database, owner, conversation_id)
    database.delete(conversation)
    database.commit()
    if owner in request.app.state.active:
        request.app.state.active[owner].cancel()


@app.get("/activity")
async def activity(database: Database, owner: Owner):
    return [
        {
            "id": attempt.id,
            "provider": attempt.provider,
            "model": attempt.model,
            "upstreams": attempt.upstreams,
            "status": attempt.status,
            "usage": attempt.usage,
            "created_at": attempt.created_at,
        }
        for attempt in database.scalars(
            select(Attempt)
            .join(Run)
            .where(
                Run.owner_id == owner,
            )
            .order_by(Attempt.created_at.desc())
            .limit(50)
        )
    ]


@app.post("/cancel", status_code=204)
async def cancel(request: Request, owner: Owner):
    task = request.app.state.active.get(owner)
    if task:
        task.cancel()


async def candidates_for(
    request: Request, owner: str, input_bytes: int, credential_id: str | None = None,
    requires_images: bool = False,
) -> list[Candidate]:
    providers = request.app.state.providers
    with Session(request.app.state.engine) as database:
        records = list(
            database.scalars(
                select(Credential)
                .where(
                    Credential.owner_id == owner,
                    Credential.approved.is_(True),
                    Credential.status != "invalid",
                )
                .order_by(Credential.priority)
            )
        )
    candidates = []
    last_error = None
    for credential in records:
        if credential_id and credential.id != credential_id:
            continue
        if requires_images and credential.provider != "copilot":
            last_error = ProviderError(Failure.INVALID, "attachment_provider_unsupported")
            continue
        if (
            credential.provider == "copilot" and credential.auth_type == "oauth"
            and credential.usage_policy == "free_only" and credential.auth_status == "authenticated"
        ):
            try:
                async with request.app.state.connection_lock:
                    with Session(request.app.state.engine) as database:
                        current = own_credential(database, owner, credential.id)
                        if not current.approved or current.upstreams != [UPSTREAM]:
                            continue
                        checked = await verify_connection(current.id, request, database, owner)
                        snapshot = checked["quota_snapshot"]
                        if snapshot["status"] != "valid":
                            code = snapshot.get("reason", "copilot_free_eligibility_unknown")
                            failure = (
                                Failure.EXHAUSTED if code == "copilot_quota_exhausted"
                                else Failure.INVALID
                            )
                            last_error = ProviderError(failure, code)
                            continue
                        candidates.append(Candidate(
                            current.id, owner, "copilot", "auto", True,
                            datetime.fromisoformat(snapshot["valid_until"]),
                            (UPSTREAM,), current.priority,
                        ))
            except ProviderError as error:
                last_error = error
            continue
        if (
            credential.auth_type != "api_key" or credential.auth_status != "authenticated"
            or credential.usage_policy != "free_only" or not credential.model
            or credential.provider not in {"openrouter", "gemini"}
        ):
            continue
        scope = quota_scope(credential)
        if not await request.app.state.limits.available(owner, scope):
            continue
        if credential.provider == "gemini":
            expiry = providers.gemini_evidence(credential.fingerprint, credential.model)
            candidates.append(
                Candidate(
                    credential.id,
                    owner,
                    credential.provider,
                    credential.model,
                    True,
                    expiry,
                    priority=credential.priority,
                )
            )
            continue
        try:
            endpoints = await providers.endpoints(credential.model)
            for endpoint in endpoints:
                if endpoint["id"] not in credential.upstreams:
                    continue
                if endpoint["context_length"] < input_bytes + 1024:
                    continue
                output_limit = endpoint.get("max_completion_tokens")
                if output_limit is not None and output_limit < 1024:
                    continue
                candidates.append(
                    Candidate(
                        credential.id,
                        owner,
                        credential.provider,
                        credential.model,
                        True,
                        datetime.now(UTC) + timedelta(seconds=60),
                        (endpoint["id"],),
                        credential.priority,
                    )
                )
        except ProviderError as error:
            last_error = error
    eligible = eligible_candidates(candidates, owner, datetime.now(UTC))
    if not eligible and last_error:
        raise last_error
    return eligible


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def execute_stream(
    request, owner, run_id, conversation_id, messages, candidates, lease, deadline=None
):
    text, final_status, provider_name, model_name = "", "interrupted", None, None
    completed_usage = None
    request.app.state.active[owner] = asyncio.current_task()
    try:
        yield sse("conversation", {"id": conversation_id})
        async with asyncio.timeout_at(deadline or asyncio.get_running_loop().time() + 60):
            for index, candidate in enumerate(candidates[:3], start=1):
                with Session(request.app.state.engine) as database:
                    credential = database.scalar(
                        select(Credential).where(
                            Credential.id == candidate.credential_id,
                            Credential.owner_id == owner,
                        )
                    )
                    if not credential or not credential.approved:
                        yield sse("error", {"code": "consent_changed"})
                        break
                    if (
                        credential.provider != candidate.provider
                        or credential.auth_status != "authenticated"
                        or credential.usage_policy != "free_only"
                        or credential.model != candidate.model
                    ):
                        yield sse("error", {"code": "consent_changed"})
                        break
                    if candidate.upstreams and not set(candidate.upstreams).issubset(
                        credential.upstreams
                    ):
                        yield sse("error", {"code": "consent_changed"})
                        break
                    scope = quota_scope(credential)
                    if candidate.provider == "copilot":
                        if credential.auth_type != "oauth":
                            yield sse("error", {"code": "consent_changed"})
                            break
                        raw_key = (await asyncio.to_thread(
                            decrypt_oauth, credential.encrypted_key, owner, credential.id,
                        ))["access_token"]
                    else:
                        raw_key = await asyncio.to_thread(
                            decrypt_key, credential.encrypted_key, owner, credential.id,
                        )
                    consent = credential.consent_version
                    fingerprint = credential.fingerprint
                endpoint_scope = f"endpoint:{candidate.credential_id}:{candidate.upstreams}"
                if not await request.app.state.limits.available(owner, scope):
                    continue
                if not await request.app.state.limits.available(owner, endpoint_scope):
                    continue
                if (
                    not candidate.free_verified_until
                    or candidate.free_verified_until <= datetime.now(UTC)
                ):
                    yield sse("error", {"code": "free_eligibility_unknown"})
                    break
                if (
                    candidate.provider == "gemini"
                    and not request.app.state.providers.gemini_evidence(
                        fingerprint,
                        candidate.model,
                    )
                ):
                    yield sse("error", {"code": "free_eligibility_unknown"})
                    break
                await request.app.state.limits.rate_limit(owner, scope, 10)
                attempt_id = identifier()
                with Session(request.app.state.engine) as database:
                    database.add(
                        Attempt(
                            id=attempt_id,
                            run_id=run_id,
                            provider=candidate.provider,
                            model=candidate.model,
                            upstreams=list(candidate.upstreams),
                            consent_version=consent,
                        )
                    )
                    database.commit()
                provider_name, model_name = candidate.provider, candidate.model
                yield sse(
                    "attempt",
                    {
                        "provider": provider_name,
                        "model": model_name,
                        "upstreams": list(candidate.upstreams),
                        "number": index,
                    },
                )
                status, usage = "interrupted", {}
                upstream_stream = request.app.state.copilot.stream(
                    raw_key, messages,
                ) if candidate.provider == "copilot" else request.app.state.providers.stream(
                    candidate.provider,
                    candidate.model,
                    raw_key,
                    messages,
                    candidate.upstreams[0] if candidate.upstreams else "",
                )
                try:
                    async for chunk in upstream_stream:
                        if await request.is_disconnected():
                            raise asyncio.CancelledError
                        if chunk["type"] == "eligibility":
                            with Session(request.app.state.engine) as database:
                                current = own_credential(database, owner, candidate.credential_id)
                                if (
                                    not current.approved or current.consent_version != consent
                                    or current.upstreams != [UPSTREAM]
                                ):
                                    raise ProviderError(Failure.INVALID, "consent_changed")
                                current.quota_snapshot = chunk["snapshot"]
                                current.status = chunk["snapshot"]["status"]
                                current.checked_at = timestamp()
                                database.commit()
                        elif chunk["type"] == "delta":
                            text += chunk["text"]
                            if len(text) > 100000:
                                raise ProviderError(Failure.INVALID, "response_too_large")
                            yield sse("delta", {"text": chunk["text"]})
                        elif chunk["type"] == "usage":
                            usage = chunk["usage"]
                            if candidate.provider == "copilot" and chunk.get("model"):
                                model_name = chunk["model"]
                                yield sse("model", {"model": model_name})
                    if not text:
                        raise ProviderError(Failure.INVALID, "empty_response")
                    status, final_status = "complete", "complete"
                    completed_usage = usage
                    break
                except ProviderError as error:
                    status = error.code
                    if candidate.provider == "copilot" and error.failure != Failure.REFUSAL:
                        with Session(request.app.state.engine) as database:
                            current = database.get(Credential, candidate.credential_id)
                            if current and current.owner_id == owner:
                                current.quota_snapshot = {
                                    **current.quota_snapshot, "status": "unverified",
                                    "reason": error.code, "source": "copilot_sdk",
                                }
                                current.status = "unverified"
                                current.checked_at = timestamp()
                                database.commit()
                    if error.failure == Failure.EXHAUSTED:
                        await request.app.state.limits.cool_down(owner, scope, error.retry_after)
                    elif error.failure == Failure.TRANSIENT:
                        await request.app.state.limits.cool_down(
                            owner, endpoint_scope, error.retry_after
                        )
                    if error.failure == Failure.AUTH:
                        with Session(request.app.state.engine) as database:
                            credential = database.get(Credential, candidate.credential_id)
                            if credential:
                                credential.status = "invalid"
                                credential.auth_status = "reauth_required"
                                database.commit()
                    if may_fallback(error.failure, bool(text), index) and index < len(candidates):
                        yield sse("fallback", {"reason": error.code})
                        continue
                    yield sse("error", {"code": error.code, "retry_after": error.retry_after})
                    break
                finally:
                    with suppress(Exception):
                        await upstream_stream.aclose()
                    with Session(request.app.state.engine) as database:
                        attempt = database.get(Attempt, attempt_id)
                        if attempt:
                            attempt.status, attempt.usage = status, usage
                            attempt.model = model_name
                            database.commit()
            else:
                yield sse("error", {"code": "rate_limited"})
    except TimeoutError:
        yield sse("error", {"code": "request_timeout"})
    except HTTPException:
        yield sse("error", {"code": "application_limit"})
    except SecretStoreError:
        yield sse("error", {"code": "secret_store_unavailable"})
    except asyncio.CancelledError:
        final_status = "cancelled"
        raise
    except Exception:
        yield sse("error", {"code": "request_failed"})
    finally:
        try:
            with Session(request.app.state.engine) as database:
                run = database.get(Run, run_id)
                if run:
                    run.status = final_status
                    if text:
                        database.add(
                            Message(
                                conversation_id=conversation_id,
                                role="assistant",
                                content=text,
                                provider=provider_name,
                                model=model_name,
                                status=final_status,
                            )
                        )
                    database.commit()
        finally:
            request.app.state.active.pop(owner, None)
            with suppress(Exception):
                await request.app.state.limits.release(owner, lease)
    if completed_usage is not None:
        yield sse("done", {"usage": completed_usage})


@app.post("/chat")
async def chat(body: ChatInput, request: Request, database: Database, owner: Owner):
    deadline = asyncio.get_running_loop().time() + 60
    await request.app.state.limits.rate_limit(owner, "chat", 10)
    run_id = f"{owner}:{body.request_id}"
    if database.get(Run, run_id):
        raise HTTPException(409, "Request already submitted")
    if body.credential_id:
        own_credential(database, owner, body.credential_id)
    conversation = None
    messages = []
    if body.conversation_id:
        conversation = own_conversation(database, owner, body.conversation_id)
        messages = [
            {"role": message.role, "content": message.content, "attachments": message.attachments}
            for message in database.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(
                    Message.created_at,
                    Message.id,
                )
            )
            if message.status == "complete"
        ]
    attachments = [attachment.model_dump() for attachment in body.attachments]
    messages.append({"role": "user", "content": body.prompt, "attachments": attachments})
    messages = prepare_messages(messages)
    input_bytes, image_bytes = context_size(messages)
    if input_bytes > 40000 or image_bytes > MAX_CONTEXT_IMAGE_BYTES or len(messages) > 80:
        raise HTTPException(422, "Conversation context limit reached; start a new conversation")
    lease = await request.app.state.limits.acquire(owner)
    try:
        async with asyncio.timeout(15):
            candidates = await candidates_for(
                request, owner, input_bytes, body.credential_id, requires_images=bool(image_bytes),
            )
        if not candidates:
            raise HTTPException(409, "No approved verified-free provider is available")
        if not conversation:
            conversation = Conversation(
                id=identifier(), owner_id=owner, title=(body.prompt or attachments[0]["name"])[:80],
            )
            database.add(conversation)
            database.flush()
        database.add(Run(id=run_id, owner_id=owner, conversation_id=conversation.id))
        database.add(Message(
            conversation_id=conversation.id, role="user", content=body.prompt,
            attachments=attachments,
        ))
        database.commit()
    except TimeoutError:
        database.rollback()
        await request.app.state.limits.release(owner, lease)
        raise HTTPException(503, "Provider preflight timed out") from None
    except IntegrityError:
        database.rollback()
        await request.app.state.limits.release(owner, lease)
        raise HTTPException(409, "Request already submitted") from None
    except BaseException:
        database.rollback()
        await request.app.state.limits.release(owner, lease)
        raise
    return StreamingResponse(
        execute_stream(
            request, owner, run_id, conversation.id, messages, candidates, lease, deadline
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
