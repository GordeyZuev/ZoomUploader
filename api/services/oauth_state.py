"""OAuth state management for CSRF protection."""

import json
import time
import uuid
from typing import Any

from logger import get_logger

logger = get_logger()


class OAuthStateManager:
    """Manages OAuth state tokens in Redis for CSRF protection."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.ttl = 600  # 10 minutes
        self.key_prefix = "oauth:state:"

    async def create_state(
        self,
        user_id: int,
        platform: str,
        ip_address: str | None = None,
    ) -> str:
        """
        Generate and store state token.

        Args:
            user_id: User ID for multi-tenancy
            platform: Platform name (youtube, vk_video)
            ip_address: Optional IP address for additional security

        Returns:
            State token (UUID)
        """
        state = str(uuid.uuid4())
        key = f"{self.key_prefix}{state}"

        metadata = {
            "user_id": user_id,
            "platform": platform,
            "created_at": int(time.time()),
        }

        if ip_address:
            metadata["ip_address"] = ip_address

        await self.redis.setex(key, self.ttl, json.dumps(metadata))

        logger.debug(f"OAuth state created: user_id={user_id} platform={platform} state={state[:8]}...")
        return state

    async def validate_state(self, state: str) -> dict[str, Any] | None:
        """
        Validate and consume state token (one-time use).

        Args:
            state: State token to validate

        Returns:
            Metadata dict if valid, None otherwise
        """
        key = f"{self.key_prefix}{state}"

        data = await self.redis.get(key)
        if not data:
            logger.warning(f"Invalid or expired OAuth state: {state[:8]}...")
            return None

        # Delete immediately (one-time use)
        await self.redis.delete(key)

        try:
            metadata = json.loads(data)
            logger.debug(f"OAuth state validated: user_id={metadata.get('user_id')} platform={metadata.get('platform')}")
            return metadata
        except json.JSONDecodeError:
            logger.error(f"Failed to parse OAuth state metadata: {state[:8]}...")
            return None

    async def cleanup_expired(self) -> int:
        """
        Cleanup expired state tokens (Redis TTL handles this automatically).

        Returns:
            Number of keys cleaned (always 0 as Redis auto-expires)
        """
        # Redis automatically removes expired keys, this is just for monitoring
        pattern = f"{self.key_prefix}*"
        keys = await self.redis.keys(pattern)
        logger.debug(f"Active OAuth states: {len(keys)}")
        return 0

