import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt and return the hash as a UTF-8 string.

    Work factor 12 is the configured cost parameter — approximately 250 ms per hash on
    modern hardware, which makes brute-force attacks impractical while remaining
    acceptable for a login flow that is rate-limited to 5 attempts/min.

    Dry run:
        password="s3cr3t" → "$2b$12$..." (60-char bcrypt hash string)
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash via constant-time comparison.

    bcrypt.checkpw is timing-safe: the comparison does not short-circuit on the first
    mismatched byte, preventing timing-oracle attacks.

    Dry run:
        password="s3cr3t", password_hash="$2b$12$..." → True   (correct password)
        password="wrong",  password_hash="$2b$12$..." → False
    """
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(
    *,
    subject: uuid.UUID,
    firm_id: uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Create a signed HS256 JWT and return it together with its remaining lifetime in seconds.

    Claims embedded in the token:
        sub     — accountant UUID (string); used to load the user on each request.
        firm_id — accountant's firm UUID; used for tenant isolation without a DB lookup.
        role    — "accountant" | "admin" | "superuser".
        iat     — issued-at Unix timestamp.
        exp     — expiry Unix timestamp (default: iat + 60 minutes).
        jti     — unique token ID; stored in Redis on logout to support revocation.

    Dry run:
        subject=UUID("acc-1"), firm_id=UUID("f-1"), role="admin"
        → ("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...", 3600)
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    claims: dict[str, Any] = {
        "sub": str(subject),
        "firm_id": str(firm_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM), int(
        (expires - now).total_seconds()
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and cryptographically verify a JWT; raise ValueError on any failure.

    PyJWT automatically validates exp (raises ExpiredSignatureError) and the signature.
    Any jwt.InvalidTokenError (expired, wrong key, malformed) is wrapped in a plain
    ValueError so callers don't need to import PyJWT exception types.

    Dry run (valid token):
        → {"sub": "acc-1", "firm_id": "f-1", "role": "admin", "jti": "...", ...}
    Dry run (expired or tampered):
        → raises ValueError("Invalid token")
    """
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except InvalidTokenError as exc:
        raise ValueError("Invalid token") from exc

