"""API authentication and authorization middleware."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from context_agent.config.settings import get_settings
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """Validate Bearer token against configured API keys.

    Returns the bearer token on success; raises 401 on failure.
    Skips validation when AUTH_ENABLED=false (dev mode).
    """
    settings = get_settings()
    if not settings.AUTH_ENABLED:
        return "anonymous"

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = credentials.credentials
    allowed = settings.API_KEYS
    if not allowed:
        # No keys configured → accept any token (soft mode)
        logger.warning("AUTH_ENABLED=true but API_KEYS is empty; accepting any token")
        return token

    if token not in allowed:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return token


# Convenience dependency alias
RequireAuth = Depends(verify_api_key)
