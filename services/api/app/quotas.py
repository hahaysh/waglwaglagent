import asyncio
import hashlib
import time
from uuid import uuid4

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError


class Limits:
    def __init__(self, redis_url: str):
        self.redis = Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        self.leases: dict[str, tuple[str, float]] = {}
        self.cooldowns: dict[str, float] = {}
        self.counters: dict[str, tuple[int, float]] = {}
        self.lock = asyncio.Lock()

    def scoped(self, owner: str, scope: str) -> str:
        return "wagl:" + hashlib.sha256(f"{owner}:{scope}".encode()).hexdigest()

    async def acquire(self, owner: str) -> str:
        key, lease = self.scoped(owner, "active"), str(uuid4())
        try:
            if self.redis:
                granted = await self.redis.set(key, lease, nx=True, ex=120)
            else:
                async with self.lock:
                    existing = self.leases.get(key)
                    granted = not existing or existing[1] < time.monotonic()
                    if granted:
                        self.leases[key] = (lease, time.monotonic() + 120)
            if not granted:
                raise HTTPException(409, "Another request is running")
            return lease
        except RedisError:
            raise HTTPException(503, "Request limits unavailable") from None

    async def release(self, owner: str, lease: str):
        key = self.scoped(owner, "active")
        if self.redis:
            await self.redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) end return 0",
                1,
                key,
                lease,
            )
        else:
            async with self.lock:
                if self.leases.get(key, (None,))[0] == lease:
                    self.leases.pop(key, None)

    async def rate_limit(self, owner: str, scope: str, maximum: int):
        key = self.scoped(owner, f"rate:{scope}")
        try:
            if self.redis:
                count = await self.redis.eval(
                    "local count = redis.call('incr', KEYS[1]); "
                    "if count == 1 then redis.call('expire', KEYS[1], 60) end return count",
                    1,
                    key,
                )
            else:
                async with self.lock:
                    count, expiry = self.counters.get(key, (0, 0))
                    if expiry < time.monotonic():
                        count, expiry = 0, time.monotonic() + 60
                    count += 1
                    self.counters[key] = (count, expiry)
                    self.counters = {
                        entry: value
                        for entry, value in self.counters.items()
                        if value[1] > time.monotonic()
                    }
            if count > maximum:
                raise HTTPException(
                    429, "Application rate limit reached", headers={"Retry-After": "60"}
                )
        except RedisError:
            raise HTTPException(503, "Request limits unavailable") from None

    async def available(self, owner: str, scope: str) -> bool:
        key = self.scoped(owner, f"cooldown:{scope}")
        try:
            if self.redis:
                return not await self.redis.exists(key)
            return self.cooldowns.get(key, 0) <= time.monotonic()
        except RedisError:
            raise HTTPException(503, "Request limits unavailable") from None

    async def cool_down(self, owner: str, scope: str, seconds: int):
        key = self.scoped(owner, f"cooldown:{scope}")
        if self.redis:
            await self.redis.set(key, "1", ex=max(1, seconds))
        else:
            self.cooldowns[key] = time.monotonic() + max(1, seconds)

    async def close(self):
        if self.redis:
            await self.redis.aclose()
