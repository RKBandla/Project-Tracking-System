"""
Authentication: password hashing, credential generation and JWT tokens.

Passwords use PBKDF2-HMAC-SHA256 from the standard library so the Lambda
package needs no native crypto dependency.
"""

import base64
import hashlib
import hmac
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt

from .errors import unauthorized

PASSWORD_LENGTH = 6
PASSWORD_ALPHABET = string.ascii_letters + string.digits
PBKDF2_ITERATIONS = 120_000
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=7)
JWT_ALGORITHM = "HS256"


def _secret() -> str:
    """Return the JWT signing secret (must be configured outside local/test)."""
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        if os.getenv("IS_LOCAL", "true") == "true":
            return "local-development-secret-change-me"
        raise RuntimeError("JWT_SECRET is not configured")
    return secret


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    """Generate a random alphanumeric password containing a letter and a digit."""
    while True:
        password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
        if any(c.isalpha() for c in password) and any(c.isdigit() for c in password):
            return password


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a password as ``pbkdf2_sha256$<iterations>$<salt>$<hash>``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against a stored hash in constant time."""
    try:
        algorithm, iterations, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def _token(user: dict, token_type: str, ttl: timedelta) -> str:
    """Create a signed JWT for a user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "role": user["role"],
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def issue_tokens(user: dict) -> dict:
    """Issue an access/refresh token pair for a user."""
    return {
        "access_token": _token(user, "access", ACCESS_TOKEN_TTL),
        "refresh_token": _token(user, "refresh", REFRESH_TOKEN_TTL),
        "token_type": "Bearer",  # nosec B105 - token type, not a secret
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
    }


def decode_token(token: str, expected_type: str) -> int:
    """Validate a token and return the user id it was issued for."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise unauthorized("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise unauthorized("Invalid token type")
    try:
        return int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise unauthorized("Invalid token") from exc


def bearer_token(headers: dict) -> str:
    """Extract the bearer token from request headers."""
    value = headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return token.strip()
