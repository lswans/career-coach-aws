"""Sign-in for the hosted coach (COACH_AUTH=cognito, set by the CloudFormation stack).

Every user route needs a Cognito access token. The browser sends it in X-Coach-Auth as well as
Authorization, because CloudFront does not pass the Authorization header to the origin on GET
requests unless it is part of the cache key, and the coach's API is never cached.

The user id comes from the token, never from the request: "u-" plus the Cognito sub (a UUID),
which fits the API's user id rule and AgentCore's actor id rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from .config import Settings


class AuthError(Exception):
    """The request has no valid sign-in. Maps to 401."""


@dataclass(frozen=True)
class Caller:
    user_id: str
    email: str


class KeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


def issuer(settings: Settings) -> str:
    region = (settings.cognito_pool_id or "").split("_", 1)[0]
    return f"https://cognito-idp.{region}.amazonaws.com/{settings.cognito_pool_id}"


def jwks_client(settings: Settings) -> KeySource:
    # Caches the pool's public keys and refetches when a token names an unknown key id.
    return jwt.PyJWKClient(f"{issuer(settings)}/.well-known/jwks.json", cache_keys=True, timeout=5)


def bearer(headers: Any) -> str:
    for name in ("x-coach-auth", "authorization"):
        value = (headers.get(name) or "").strip()
        if value.lower().startswith("bearer "):
            return value[7:].strip()
    raise AuthError("Sign in to use your coach.")


def verify(token: str, settings: Settings, keys: KeySource) -> Caller:
    """Check the signature, issuer, expiry, token type and app client, as Cognito's docs describe."""
    try:
        key = keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=issuer(settings),
                            options={"require": ["exp", "iss", "sub", "token_use", "client_id"]})
    except jwt.PyJWTError as exc:
        raise AuthError("Your sign-in has expired. Sign in again.") from exc
    if claims.get("token_use") != "access" or claims.get("client_id") != settings.cognito_client_id:
        raise AuthError("Sign in to use your coach.")
    sub = str(claims["sub"]).lower()
    return Caller(user_id=f"u-{sub}"[:63], email=str(claims.get("username", "")))
