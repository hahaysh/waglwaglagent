import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings
from app.routing import Failure


class ProviderError(Exception):
    def __init__(self, failure: Failure, code: str, retry_after: int = 30):
        self.failure = failure
        self.code = code
        self.retry_after = min(max(retry_after, 1), 86400)
        super().__init__(code)


def zero_pricing(pricing: dict) -> bool:
    if not isinstance(pricing, dict) or not {"prompt", "completion"}.issubset(pricing):
        return False
    try:
        return all(
            Decimal(str(value)).is_finite() and Decimal(str(value)) == 0
            for key, value in pricing.items()
            if key != "discount"
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


class Providers:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15, follow_redirects=False)
        self.catalog: dict | None = None
        self.catalog_expires = datetime.min.replace(tzinfo=UTC)
        self.catalog_lock = asyncio.Lock()

    async def free_models(self) -> dict:
        async with self.catalog_lock:
            if self.catalog and self.catalog_expires > datetime.now(UTC):
                return self.catalog
            try:
                response = await self.client.get("https://openrouter.ai/api/v1/models")
                response.raise_for_status()
                models = [
                    {
                        "id": model["id"],
                        "name": model["name"],
                        "context_length": model.get("context_length", 0),
                    }
                    for model in response.json()["data"]
                    if model["id"].endswith(":free")
                    and zero_pricing(model.get("pricing", {}))
                    and model.get("architecture", {}).get("output_modalities") == ["text"]
                ]
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                raise ProviderError(Failure.TRANSIENT, "catalog_unavailable") from None
            self.catalog_expires = datetime.now(UTC) + timedelta(seconds=60)
            self.catalog = {
                "models": sorted(models, key=lambda model: model["name"]),
                "checked_at": datetime.now(UTC).isoformat(),
            }
            return self.catalog

    async def endpoints(self, model: str) -> list[dict]:
        catalog = await self.free_models()
        if model not in {entry["id"] for entry in catalog["models"]}:
            raise ProviderError(Failure.INVALID, "model_not_free")
        try:
            response = await self.client.get(
                f"https://openrouter.ai/api/v1/models/{model}/endpoints"
            )
            response.raise_for_status()
            return [
                {
                    "id": endpoint["tag"],
                    "name": endpoint["provider_name"],
                    "context_length": endpoint.get("context_length", 0),
                    "max_completion_tokens": endpoint.get("max_completion_tokens"),
                }
                for endpoint in response.json()["data"]["endpoints"]
                if endpoint.get("tag")
                and zero_pricing(endpoint.get("pricing", {}))
                and "max_tokens" in endpoint.get("supported_parameters", [])
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise ProviderError(Failure.TRANSIENT, "endpoints_unavailable") from None

    async def validate(self, provider: str, raw_key: str) -> dict:
        try:
            if provider == "openrouter":
                response = await self.client.get(
                    "https://openrouter.ai/api/v1/key",
                    headers={"Authorization": f"Bearer {raw_key}"},
                )
            else:
                response = await self.client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": raw_key},
                )
            if response.status_code in {400, 401, 403}:
                raise ProviderError(Failure.AUTH, "invalid_key")
            response.raise_for_status()
            if provider == "gemini":
                return {"status": "unverified", "source": "billing_tier_unknown"}
            data = response.json()["data"]
            daily = data.get("free_model_daily_requests")
            return {
                "status": "valid",
                "source": "official",
                "daily": daily if isinstance(daily, dict) else None,
                "checked_at": datetime.now(UTC).isoformat(),
            }
        except ProviderError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise ProviderError(Failure.TRANSIENT, "verification_unavailable") from None

    def gemini_evidence(self, fingerprint: str, model: str) -> datetime | None:
        review = get_settings().gemini_reviews.get(fingerprint, {})
        try:
            expiry = datetime.fromisoformat(review["expires_at"])
            if expiry.tzinfo and model in review["models"] and expiry > datetime.now(UTC):
                return min(expiry, datetime.now(UTC) + timedelta(minutes=5))
        except (KeyError, TypeError, ValueError):
            pass
        return None

    async def stream(self, provider: str, model: str, raw_key: str, messages: list, upstream: str):
        import litellm

        litellm.telemetry = False
        litellm.suppress_debug_info = True
        extra = {}
        if provider == "openrouter":
            extra = {
                "extra_body": {
                    "provider": {
                        "only": [upstream],
                        "order": [upstream],
                        "allow_fallbacks": False,
                        "require_parameters": True,
                        "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
                    },
                },
                "api_base": "https://openrouter.ai/api/v1",
            }
        stream = None
        try:
            stream = await litellm.acompletion(
                model=f"{provider}/{model}",
                api_key=raw_key,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=1024,
                timeout=30,
                num_retries=0,
                caching=False,
                **extra,
            )
            async for chunk in stream:
                payload = chunk.model_dump()
                if payload.get("error"):
                    raise ProviderError(Failure.INVALID, "upstream_stream_error")
                for choice in payload.get("choices", []):
                    if choice.get("finish_reason") == "content_filter" or choice.get(
                        "delta", {}
                    ).get("refusal"):
                        raise ProviderError(Failure.REFUSAL, "policy_refusal")
                    if choice.get("finish_reason") == "error":
                        raise ProviderError(Failure.INVALID, "upstream_stream_error")
                    content = choice.get("delta", {}).get("content")
                    if isinstance(content, str) and content:
                        yield {"type": "delta", "text": content}
                if payload.get("usage"):
                    usage = payload["usage"]
                    yield {
                        "type": "usage",
                        "usage": {
                            key: usage[key]
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                            if isinstance(usage.get(key), int)
                        },
                    }
        except ProviderError:
            raise
        except Exception as error:
            status = getattr(error, "status_code", None)
            if isinstance(error, litellm.ContentPolicyViolationError):
                raise ProviderError(Failure.REFUSAL, "policy_refusal") from None
            if status in {401, 403}:
                raise ProviderError(Failure.AUTH, "invalid_key") from None
            if status == 429:
                headers = getattr(getattr(error, "response", None), "headers", {})
                try:
                    retry_after = int(headers.get("retry-after", 30))
                except (TypeError, ValueError):
                    retry_after = 30
                raise ProviderError(Failure.EXHAUSTED, "rate_limited", retry_after) from None
            if status in {500, 502, 503, 504} or isinstance(
                error, (litellm.Timeout, litellm.APIConnectionError)
            ):
                raise ProviderError(Failure.TRANSIENT, "provider_unavailable") from None
            raise ProviderError(Failure.INVALID, "provider_rejected_request") from None
        finally:
            if stream:
                close = getattr(stream, "aclose", None)
                if close:
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    async def close(self):
        await self.client.aclose()
