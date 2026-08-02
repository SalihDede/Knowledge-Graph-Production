from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis


FIXED_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RedisFixedWindowRateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        current, ttl = await self.redis.eval(
            FIXED_WINDOW_SCRIPT,
            1,
            key,
            window_seconds,
        )
        current = int(current)
        ttl = max(int(ttl), 1)
        return RateLimitResult(
            allowed=current <= limit,
            limit=limit,
            remaining=max(limit - current, 0),
            retry_after=ttl,
        )
