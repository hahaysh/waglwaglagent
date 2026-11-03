from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from app.quotas import Limits


@pytest.mark.asyncio
async def test_lease_is_owner_scoped_and_stale_release_cannot_delete_new_lease():
    limits = Limits("")
    first = await limits.acquire("alice")
    second = await limits.acquire("bob")
    with pytest.raises(HTTPException) as error:
        await limits.acquire("alice")
    assert error.value.status_code == 409
    await limits.release("alice", first)
    replacement = await limits.acquire("alice")
    await limits.release("alice", first)
    with pytest.raises(HTTPException):
        await limits.acquire("alice")
    await limits.release("alice", replacement)
    await limits.release("bob", second)


@pytest.mark.asyncio
async def test_limits_fail_closed_when_redis_is_unavailable():
    limits = Limits("")
    limits.redis = AsyncMock()
    limits.redis.set.side_effect = ConnectionError("unavailable")
    limits.redis.exists.side_effect = ConnectionError("unavailable")
    limits.redis.eval.side_effect = ConnectionError("unavailable")
    for operation in [
        limits.acquire("alice"),
        limits.available("alice", "account"),
        limits.rate_limit("alice", "chat", 10),
    ]:
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 503
