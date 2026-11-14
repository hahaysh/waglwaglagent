import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.providers import ProviderError, Providers, zero_pricing


def test_free_pricing_fails_closed():
    assert zero_pricing({"prompt": "0", "completion": "0", "discount": 0.5})
    for pricing in [
        {},
        {"prompt": "0"},
        {"prompt": "0", "completion": "1"},
        {"prompt": "0", "completion": "0", "request": "0.01"},
        {"prompt": "NaN", "completion": "0"},
        {"prompt": "0", "completion": "0", "new_fee": None},
    ]:
        assert not zero_pricing(pricing)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,host", [
    ("openai", "api.openai.com"), ("anthropic", "api.anthropic.com"),
    ("gemini", "generativelanguage.googleapis.com"),
])
async def test_key_verification_never_generates_or_claims_free_usage(provider, host):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET" and request.url.host == host
        return httpx.Response(200, json={"models" if provider == "gemini" else "data": []})

    providers = Providers()
    await providers.client.aclose()
    providers.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await providers.validate(provider, "test-secret")
        assert result["status"] == "unverified"
        assert result["source"] == "billing_tier_unknown"
        assert len(requests) == 1
    finally:
        await providers.close()


@pytest.mark.asyncio
async def test_key_permission_error_is_not_mislabeled_invalid_key():
    providers = Providers()
    await providers.client.aclose()
    providers.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _request: httpx.Response(403)
    ))
    try:
        with pytest.raises(ProviderError, match="provider_permission_denied"):
            await providers.validate("openai", "test-secret")
    finally:
        await providers.close()


@pytest.mark.asyncio
async def test_litellm_receives_per_request_keys_and_hard_upstream_restrictions(monkeypatch):
    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            pass

    completion = AsyncMock(side_effect=lambda **kwargs: Stream())
    fake = SimpleNamespace(acompletion=completion)
    monkeypatch.setitem(sys.modules, "litellm", fake)
    providers = Providers()
    try:
        for raw_key in ("alice-secret", "bob-secret"):
            async for _chunk in providers.stream(
                "openrouter",
                "vendor/model:free",
                raw_key,
                [{"role": "user", "content": "hello"}],
                "approved/bf16",
            ):
                pass
        calls = completion.call_args_list
        assert [call.kwargs["api_key"] for call in calls] == ["alice-secret", "bob-secret"]
        for call in calls:
            preferences = call.kwargs["extra_body"]["provider"]
            assert preferences["only"] == ["approved/bf16"]
            assert preferences["allow_fallbacks"] is False
            assert preferences["max_price"]["request"] == 0
            assert call.kwargs["num_retries"] == 0
            assert "plugins" not in call.kwargs["extra_body"]
    finally:
        await providers.close()


@pytest.mark.asyncio
async def test_actual_sdk_http_contract_and_parallel_key_isolation(monkeypatch):
    monkeypatch.setenv("LITELLM_TELEMETRY", "False")
    requests = []

    async def intercept(_client, request, **_kwargs):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        body = json.loads(request.content)
        requests.append((request.headers["authorization"], body))
        chunks = [
            {
                "id": "test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/model:free",
                "choices": [
                    {"index": 0, "delta": {"content": "테스트"}, "finish_reason": None},
                ],
            },
            {
                "id": "test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/model:free",
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "stop"},
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        ]
        content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(
            200,
            request=request,
            content=content.encode(),
            headers={"content-type": "text/event-stream"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", intercept)
    providers = Providers()

    async def collect(raw_key):
        return [
            chunk
            async for chunk in providers.stream(
                "openrouter",
                "vendor/model:free",
                raw_key,
                [{"role": "user", "content": "hello"}],
                "approved/bf16",
            )
        ]

    try:
        results = await asyncio.gather(collect("alice-test-key"), collect("bob-test-key"))
        assert {authorization for authorization, _body in requests} == {
            "Bearer alice-test-key",
            "Bearer bob-test-key",
        }
        assert len(requests) == 2
        for _authorization, body in requests:
            assert body["model"] == "vendor/model:free"
            assert body["provider"]["only"] == ["approved/bf16"]
            assert body["provider"]["allow_fallbacks"] is False
            assert body["provider"]["max_price"]["request"] == 0
            assert "plugins" not in body
        for result in results:
            assert {"type": "delta", "text": "테스트"} in result
            assert any(chunk.get("usage", {}).get("total_tokens") == 3 for chunk in result)
    finally:
        await providers.close()
