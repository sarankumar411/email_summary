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
    if current_user.role not in {"admin", "superuser"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


async def require_superuser(current_user: CurrentUser) -> AuthenticatedUser:
    if current_user.role != "superuser":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser role required")
    return current_user


AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
Superuser = Annotated[AuthenticatedUser, Depends(require_superuser)]
