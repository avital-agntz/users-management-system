import json
import logging

import redis
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.schemas import UserResponse

settings = get_settings()
logger = logging.getLogger(__name__)

# configure Redis client
redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def cache_profile(profile: dict) -> None:
    """
    Caches the profile data dict as JSON in Redis with a TTL
    """
    key = f"users-management:profile:{profile['id']}"
    value = json.dumps(profile)

    try:
        # store the profile data in Redis with expiration time
        redis_client.set(
            key,
            value,
            ex=settings.profile_cache_ttl_seconds,
        )
    except RedisError:
        logger.warning("Could not write the updated profile to Redis.")

        # Remove the potentially outdated cached copy.
        try:
            redis_client.delete(key)
        except RedisError:
            logger.warning("Could not delete the outdated cached profile.")


def get_cached_profile(user_id: int) -> UserResponse | None:
    """
    Returns a validated profile belonging to user_id, or None for a cache miss.
    """
    key = f"users-management:profile:{user_id}"

    try:
        # attempt to retrieve the cached profile data from Redis
        value = redis_client.get(key)
    except RedisError as e:
        logger.warning(
            f"Failed to retrieve cached profile data for user {user_id}: {e}"
        )
        return None

    # if the profile does not exist in the cache, return None
    if value is None:
        return None

    try:
        # attempt to parse the cached JSON string into a Python dictionary
        profile = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Profile cache contains invalid JSON.")
        return None

    # makes sure the cached profile is a dictionary
    if not isinstance(profile, dict):
        logger.warning("Cached profile is not a dictionary.")
        return None

    try:
        # validate the cached profile data against the UserResponse model
        validated_profile = UserResponse.model_validate(profile)
    except ValidationError:
        logger.warning("Cached profile contains invalid fields.")
        return None

    # Never return another user's profile
    if validated_profile.id != user_id:
        logger.warning("Cached profile ID does not match the requested user.")
        return None

    return validated_profile
