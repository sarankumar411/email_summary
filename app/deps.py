import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import AuthenticatedUser
from app.core.cache import CacheService
from app.core.security import decode_access_token
from app.db.session import get_read_session, get_write_session
from app.modules.clients.service import ClientsService
from app.modules.identity.service import IdentityService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_read_db() -> AsyncIterator[AsyncSession]:
    async for session in get_read_session():
        yield session


async def get_write_db() -> AsyncIterator[AsyncSession]:
    async for session in get_write_session():
        yield session


ReadDb = Annotated[AsyncSession, Depends(get_read_db)]
WriteDb = Annotated[AsyncSession, Depends(get_write_db)]


async def get_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict:
    """Extract and validate the Bearer token; check the Redis JTI blocklist for revocation.

    Steps:
        1. If the Authorization header is absent → 401 Missing bearer token.
        2. Decode and verify the JWT signature + expiry → 401 Invalid bearer token on failure.
        3. If the token's jti is present in Redis "auth:blocklist:{jti}" → 401 Token revoked.
           (Redis errors are silently ignored; a Redis outage should not block all API access.)

    Returns the raw JWT payload dict on success.

    Dry run (valid, non-revoked token):
        → {"sub": "acc-1", "firm_id": "f-1", "role": "admin", "jti": "...", "exp": ...}
    Dry run (expired or tampered token):
        → raises HTTP 401
    Dry run (token in blocklist after logout):
        → raises HTTP 401 "Token has been revoked"
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token") from exc

    jti = payload.get("jti")
    if jti:
        try:
            if await CacheService().get_json(f"auth:blocklist:{jti}") is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                )
        except RedisError:
            pass
    return payload


async def get_current_user(
    payload: Annotated[dict, Depends(get_token_payload)],
    session: ReadDb,
) -> AuthenticatedUser:
    """Load the active accountant from the DB using the sub claim from the verified JWT.

    Depends on get_token_payload (JWT already verified and blocklist-checked by the time
    this runs). Converts the sub string claim to a UUID and fetches the accountant from the
    read replica. Returns None (→ 401) if the account has been deactivated since the token
    was issued — the JWT alone is not enough; the DB is the source of truth for is_active.

    Dry run (valid JWT, active account):
        payload.sub="acc-1" → AuthenticatedUser(id=UUID("acc-1"), role="admin", is_active=True)
    Dry run (account deactivated after token issue):
        → raises HTTP 401 "Inactive account"
    """
    try:
        accountant_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    accountant = await IdentityService(session).get_active_accountant_context(accountant_id)
    if accountant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive account")
    return accountant


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
TokenPayload = Annotated[dict, Depends(get_token_payload)]


def get_identity_service(session: WriteDb) -> IdentityService:
    return IdentityService(session)


def get_clients_service(session: WriteDb) -> ClientsService:
    return ClientsService(session)


def get_clients_read_service(session: ReadDb) -> ClientsService:
    return ClientsService(session)


async def require_admin(current_user: CurrentUser) -> AuthenticatedUser:
    """Guard dependency: raise 403 unless the caller holds admin or superuser role.

    Used on endpoints that manage assignments and accountants at the firm level.

    Dry run (role="admin")     → passes through, returns current_user.
    Dry run (role="accountant") → raises HTTP 403 "Admin role required".
    """
    if current_user.role not in {"admin", "superuser"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


async def require_superuser(current_user: CurrentUser) -> AuthenticatedUser:
    """Guard dependency: raise 403 unless the caller is a superuser.

    Used exclusively on the global report endpoint, which spans all firms.

    Dry run (role="superuser") → passes through, returns current_user.
    Dry run (role="admin")     → raises HTTP 403 "Superuser role required".
    """
    if current_user.role != "superuser":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser role required")
    return current_user


AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
Superuser = Annotated[AuthenticatedUser, Depends(require_superuser)]
