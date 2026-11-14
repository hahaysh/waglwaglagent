import asyncio
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from copilot.generated.rpc import (
    AccountGetQuotaResult,
    AccountQuotaSnapshot,
    PermissionDecisionReject,
    SessionAuthStatus,
)
from copilot.generated.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantUsageData,
    SessionErrorData,
)
from PIL import Image

from app.copilot_provider import CopilotProvider, assess_quota
from app.providers import ProviderError


def quota_bucket(**changes):
    return AccountQuotaSnapshot(**{
        "entitlement_requests": 50, "used_requests": 10, "remaining_percentage": 80,
        "overage": 0, "overage_allowed_with_exhausted_quota": False,
        "usage_allowed_with_exhausted_quota": False, "is_unlimited_entitlement": False,
    } | changes)


def free_quota():
    return AccountGetQuotaResult({
        "chat": quota_bucket(), "premium_interactions": quota_bucket(),
    })


@pytest.mark.parametrize("plan", ["free", "individual", "enterprise", "business", None])
@pytest.mark.parametrize("overage_allowed", [False, True])
def test_included_usage_is_allowed_by_remaining_quota_not_plan_or_overage_setting(
    plan, overage_allowed,
):
    quota = free_quota()
    quota.quota_snapshots["premium_interactions"] = quota_bucket(
        overage_allowed_with_exhausted_quota=overage_allowed,
    )
    result = assess_quota(SessionAuthStatus(True, copilot_plan=plan), quota)
    assert result["status"] == "valid"
    assert result["reason"] == "available"
    assert result["plan"] == plan
    assert result["overage_allowed"] is overage_allowed


@pytest.mark.parametrize("changes,reason", [
    ({"overage": 1}, "copilot_overage_in_use"),
    ({"remaining_percentage": 0}, "copilot_quota_exhausted"),
    ({"entitlement_requests": 0}, "copilot_quota_exhausted"),
    ({"used_requests": 50}, "copilot_quota_exhausted"),
    ({"used_requests": 51}, "copilot_quota_exhausted"),
    ({"remaining_percentage": float("nan")}, "copilot_free_eligibility_unknown"),
    ({"remaining_percentage": -1}, "copilot_free_eligibility_unknown"),
])
@pytest.mark.parametrize("plan", ["free", "individual", "enterprise"])
def test_included_usage_policy_checks_chat_and_premium_buckets(changes, reason, plan):
    for key in ("chat", "premium_interactions"):
        quota = free_quota()
        quota.quota_snapshots[key] = quota_bucket(**changes)
        result = assess_quota(SessionAuthStatus(True, copilot_plan=plan), quota)
        assert result["status"] == "unverified"
        assert result["reason"] == reason


def test_missing_quota_and_authentication_fail_closed_without_inventing_balance():
    quota = free_quota()
    del quota.quota_snapshots["premium_interactions"]
    result = assess_quota(SessionAuthStatus(True, copilot_plan="free"), quota)
    assert result["reason"] == "copilot_free_eligibility_unknown"
    assert "quotas" not in result
    result = assess_quota(SessionAuthStatus(False, copilot_plan="free"), free_quota())
    assert result["reason"] == "reauth_required"


@pytest.fixture
def runtime(monkeypatch):
    state = SimpleNamespace(
        quota=free_quota(), auth=SessionAuthStatus(True, copilot_plan="free"),
        clients=[], sends=[], mode="complete", started=asyncio.Event(),
        attachments=[],
    )

    class FakeSession:
        session_id = "isolated-test-session"

        def __init__(self):
            self.handler = None
            self.aborted = False
            self.rpc = SimpleNamespace(git_hub_auth=SimpleNamespace(get_status=self.auth))

        async def auth(self, **_kwargs):
            return state.auth

        def on(self, handler):
            self.handler = handler
            return lambda: setattr(self, "handler", None)

        async def send_and_wait(self, prompt, **_kwargs):
            state.sends.append(json.loads(prompt))
            state.attachments.append(_kwargs.get("attachments"))
            for value in ("안녕", "하세요"):
                self.handler(SimpleNamespace(
                    agent_id=None,
                    data=AssistantMessageDeltaData(delta_content=value, message_id="answer"),
                ))
            state.started.set()
            if state.mode == "wait":
                await asyncio.Event().wait()
            if state.mode == "exhausted":
                self.handler(SimpleNamespace(agent_id=None, data=SessionErrorData(
                    error_type="provider", message="must-not-leak-provider-secret", status_code=429,
                )))
                raise RuntimeError("must-not-leak-provider-secret")
            self.handler(SimpleNamespace(agent_id=None, data=AssistantUsageData(
                model="free-auto-model", input_tokens=8, output_tokens=3,
            )))
            if state.mode == "multi-call":
                self.handler(SimpleNamespace(agent_id=None, data=AssistantUsageData(
                    model="free-auto-model", input_tokens=4, output_tokens=2,
                )))
            self.handler(SimpleNamespace(agent_id=None, data=AssistantMessageData(
                content="안녕하세요", message_id="answer",
            )))

        async def abort(self):
            self.aborted = True

    class FakeClient:
        def __init__(self, **options):
            self.options = options
            self.stopped = False
            self.session = FakeSession()
            self.rpc = SimpleNamespace(account=SimpleNamespace(get_quota=self.quota))
            state.clients.append(self)

        async def start(self):
            pass

        async def quota(self, params, **_kwargs):
            assert params.git_hub_token == self.options["github_token"]
            return state.quota

        async def create_session(self, **options):
            self.session_options = options
            return self.session

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr("app.copilot_provider.CopilotClient", FakeClient)
    return state


@pytest.mark.asyncio
async def test_adapter_options_streaming_context_and_user_token_isolation(runtime, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-user-must-not-be-used")
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", "master-key-must-not-be-inherited")
    provider = CopilotProvider()
    messages = [{"role": "user", "content": "한국어 테스트"}]
    for token in ("gho_alice", "gho_bob"):
        chunks = [chunk async for chunk in provider.stream(token, messages)]
        assert chunks[0]["snapshot"]["status"] == "valid"
        text = "".join(chunk["text"] for chunk in chunks if chunk["type"] == "delta")
        assert text == "안녕하세요"
        assert [chunk["usage"] for chunk in chunks if chunk["type"] == "usage"] == [{
            "prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11,
        }]
        client = runtime.clients[-1]
        assert client.options["github_token"] == token
        assert client.options["use_logged_in_user"] is False
        assert client.options["mode"] == "empty"
        assert "GITHUB_TOKEN" not in client.options["env"]
        assert "WAGL_ENCRYPTION_KEY" not in client.options["env"]
        assert not Path(client.options["base_directory"]).exists()
        options = client.session_options
        assert options["github_token"] == token
        assert options["available_tools"] == []
        assert options["excluded_tools"] == ["builtin:*", "mcp:*", "custom:*"]
        assert options["enable_config_discovery"] is False
        assert options["enable_skills"] is False
        assert options["auto_mode_recovery"] is False
        assert isinstance(options["on_permission_request"](None, None), PermissionDecisionReject)
        assert client.stopped
    assert runtime.sends == [messages, messages]
    directories = {client.options["base_directory"] for client in runtime.clients}
    assert len(directories) == 2


@pytest.mark.asyncio
async def test_image_context_is_sent_as_sdk_blob_not_base64_prompt_or_local_file(runtime):
    import base64

    image = BytesIO()
    Image.new("RGB", (4, 4), "red").save(image, format="PNG")
    data = base64.b64encode(image.getvalue()).decode()
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "이전 이미지"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        ]},
        {"role": "assistant", "content": "빨강"},
        {"role": "user", "content": "같은 이미지의 색을 다시 알려줘"},
    ]
    _chunks = [chunk async for chunk in CopilotProvider().stream("gho_test", messages)]
    assert runtime.attachments == [[{
        "type": "blob", "mimeType": "image/png", "data": data,
        "displayName": "conversation-image-1",
    }]]
    assert data not in json.dumps(runtime.sends)
    assert runtime.sends[0][0]["role"] == "user"
    assert "conversation-image-1" in runtime.sends[0][0]["content"]
    assert runtime.sends[0][-1] == messages[-1]


@pytest.mark.asyncio
async def test_enterprise_included_chat_with_overage_setting_and_exhaustion_before_model_call(
    runtime,
):
    provider = CopilotProvider()
    runtime.auth = replace(runtime.auth, copilot_plan="enterprise")
    runtime.quota.quota_snapshots["premium_interactions"] = quota_bucket(
        overage_allowed_with_exhausted_quota=True,
    )
    assert (await provider.verify("gho_test"))["status"] == "valid"
    messages = [{"role": "user", "content": "Hi"}]
    chunks = [chunk async for chunk in provider.stream("gho_test", messages)]
    assert any(chunk["type"] == "delta" for chunk in chunks)
    runtime.sends.clear()
    runtime.quota.quota_snapshots["premium_interactions"] = quota_bucket(
        remaining_percentage=0, used_requests=50, overage_allowed_with_exhausted_quota=True,
    )
    with pytest.raises(ProviderError, match="copilot_quota_exhausted"):
        async for _chunk in provider.stream("gho_test", messages):
            pass
    assert runtime.sends == []
    assert runtime.clients[-1].stopped


@pytest.mark.asyncio
async def test_stream_close_aborts_active_turn_and_removes_temporary_state(runtime):
    runtime.mode = "wait"
    stream = CopilotProvider().stream("gho_test", [{"role": "user", "content": "Hi"}])
    assert (await anext(stream))["type"] == "eligibility"
    assert (await anext(stream))["type"] == "delta"
    await stream.aclose()
    client = runtime.clients[0]
    assert client.session.aborted and client.stopped
    assert not Path(client.options["base_directory"]).exists()


@pytest.mark.asyncio
async def test_usage_totals_include_every_sdk_model_call(runtime):
    runtime.mode = "multi-call"
    chunks = [chunk async for chunk in CopilotProvider().stream(
        "gho_test", [{"role": "user", "content": "Hi"}],
    )]
    usage = [chunk for chunk in chunks if chunk["type"] == "usage"]
    assert usage[-1]["usage"] == {
        "prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
    }
    assert usage[-1]["model"] == "free-auto-model"


@pytest.mark.asyncio
async def test_provider_error_is_classified_without_returning_raw_sdk_message(runtime):
    runtime.mode = "exhausted"
    with pytest.raises(ProviderError, match="copilot_quota_exhausted") as error:
        async for _chunk in CopilotProvider().stream(
            "gho_test", [{"role": "user", "content": "Hi"}],
        ):
            pass
    assert "must-not-leak" not in str(error.value)
