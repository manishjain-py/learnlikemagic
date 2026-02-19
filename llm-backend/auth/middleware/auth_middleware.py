"""
JWT validation middleware for AWS Cognito tokens.

Token types:
  - Access token (token_use="access"): Used for all API calls. Has `client_id` claim.
  - ID token (token_use="id"): Used only for /auth/sync. Has `aud` claim + user attributes.

Usage:
    @router.get("/protected")
    def protected_endpoint(current_user: User = Depends(get_current_user)):
        return {"user_id": current_user.id}
"""

import logging
import time
from typing import Optional, Literal
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import httpx

from config import get_settings
from auth.repositories.user_repository import UserRepository
from database import get_db
from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger("auth.middleware")

security = HTTPBearer(auto_error=False)

# JWKS cache with TTL
_jwks_cache: Optional[dict] = None
_jwks_fetched_at: float = 0
JWKS_TTL_SECONDS = 3600  # Re-fetch keys every hour


async def _get_jwks(force_refresh: bool = False) -> dict:
    """
    Fetch and cache Cognito JWKS (JSON Web Key Set).

    Uses a TTL-based cache (1 hour) with refresh-on-miss:
    - Normal: serve from cache if within TTL
    - force_refresh=True: bypass cache (used when kid not found, indicating key rotation)
    """
    global _jwks_cache, _jwks_fetched_at
    now = time.time()

    if _jwks_cache and not force_refresh and (now - _jwks_fetched_at < JWKS_TTL_SECONDS):
        return _jwks_cache

    settings = get_settings()
    jwks_url = (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(jwks_url)
        _jwks_cache = response.json()
        _jwks_fetched_at = now

    logger.info("JWKS cache refreshed")
    return _jwks_cache


async def _verify_cognito_token(
    token: str,
    expected_token_use: Literal["access", "id"] = "access",
) -> dict:
    """
    Verify a Cognito JWT and return claims.

    Args:
        token: The JWT string
        expected_token_use: "access" for API calls, "id" for /auth/sync
    """
    settings = get_settings()

    # Skip JWT validation if Cognito is not configured (development mode)
    if not settings.cognito_user_pool_id:
        raise HTTPException(status_code=401, detail="Authentication not configured")

    jwks = await _get_jwks()

    # Decode header to get key ID
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")

    # Find matching key
    key = None
    for k in jwks.get("keys", []):
        if k["kid"] == kid:
            key = k
            break

    # Key not found — might be a key rotation. Refresh JWKS once and retry.
    if not key:
        logger.warning(f"kid '{kid}' not found in JWKS cache, refreshing...")
        jwks = await _get_jwks(force_refresh=True)
        for k in jwks.get("keys", []):
            if k["kid"] == kid:
                key = k
                break

    if not key:
        raise HTTPException(status_code=401, detail="Invalid token: key not found after refresh")

    # Verify token — audience/client_id validation differs by token type
    issuer = (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}"
    )

    try:
        if expected_token_use == "id":
            # ID tokens have `aud` = app client ID
            # Skip at_hash verification — it requires the access_token to be passed
            # to decode(), but we validate both tokens independently.
            claims = jwt.decode(
                token, key, algorithms=["RS256"],
                audience=settings.cognito_app_client_id,
                issuer=issuer,
                options={"verify_at_hash": False},
            )
        else:
            # Access tokens have `client_id` (not `aud`) — skip audience check in decode,
            # validate client_id manually after
            claims = jwt.decode(
                token, key, algorithms=["RS256"],
                issuer=issuer,
                options={"verify_aud": False},
            )
            if claims.get("client_id") != settings.cognito_app_client_id:
                raise HTTPException(status_code=401, detail="Invalid token: wrong client_id")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Validate token_use claim
    actual_token_use = claims.get("token_use")
    if actual_token_use != expected_token_use:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: expected token_use='{expected_token_use}', got '{actual_token_use}'"
        )

    return claims


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DBSession = Depends(get_db),
):
    """
    FastAPI dependency: extract and validate access token, return User from DB.
    Raises 401 if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    claims = await _verify_cognito_token(credentials.credentials, expected_token_use="access")
    cognito_sub = claims.get("sub")

    if not cognito_sub:
        raise HTTPException(status_code=401, detail="Invalid token: no sub claim")

    # Look up user in our DB
    repo = UserRepository(db)
    user = repo.get_by_cognito_sub(cognito_sub)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Call /auth/sync first."
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DBSession = Depends(get_db),
):
    """
    Same as get_current_user but returns None instead of 401 for unauthenticated.
    Use for endpoints that work for both authenticated and anonymous users.
    """
    if not credentials:
        return None

    try:
        claims = await _verify_cognito_token(credentials.credentials, expected_token_use="access")
        cognito_sub = claims.get("sub")
        if cognito_sub:
            repo = UserRepository(db)
            return repo.get_by_cognito_sub(cognito_sub)
    except HTTPException:
        pass

    return None
