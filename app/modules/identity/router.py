import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.exceptions import RedisError
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings
from app.core.cache import CacheService
from app.core.exceptions import AuthorizationError, NotFoundError
from app.deps import AdminUser, CurrentUser, TokenPayload, get_clients_service, get_identity_service
from app.modules.clients.service import ClientsService
from app.modules.identity.schemas import (
    AccountantOut,
    AccountantUpdateRequest,
    AssignmentListResponse,
    AssignmentReplaceRequest,
    LoginRequest,
    TokenResponse,
)
from app.modules.identity.service import IdentityService

router = APIRouter(tags=["identity"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/auth/login", response_model=TokenResponse)
@limiter.limit(get_settings().login_rate_limit)
async def login(
    request: Request,
    payload: LoginRequest,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> TokenResponse:
    del request
    try:
        token, expires_in = await service.authenticate(payload.email, payload.password)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        ) from exc
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: TokenPayload) -> Response:
    jti = payload.get("jti")
    exp = int(payload.get("exp", 0))
    if jti and exp:
        ttl = max(exp - int(__import__("time").time()), 1)
        try:
            await CacheService().set_json(f"auth:blocklist:{jti}", {"revoked": True}, ttl)
        except RedisError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis unavailable") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/accountants/{accountant_id}", response_model=AccountantOut)
async def update_accountant(
    accountant_id: uuid.UUID,
    payload: AccountantUpdateRequest,
    current_user: CurrentUser,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AccountantOut:
    try:
        accountant = await service.update_accountant(accountant_id, payload, current_user)
        return AccountantOut.model_validate(accountant)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Accountant not found") from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.put("/accountants/{accountant_id}/assignments", response_model=AssignmentListResponse)
async def replace_assignments(
    accountant_id: uuid.UUID,
    payload: AssignmentReplaceRequest,
    current_user: AdminUser,
    service: Annotated[ClientsService, Depends(get_clients_service)],
) -> AssignmentListResponse:
    try:
        assignments = await service.replace_assignments(
            target_accountant_id=accountant_id,
            client_ids=payload.client_ids,
            current_user=current_user,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found") from exc
    return AssignmentListResponse(accountant_id=accountant_id, client_ids=assignments)


@router.delete(
    "/accountants/{accountant_id}/assignments/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_assignment(
    accountant_id: uuid.UUID,
    client_id: uuid.UUID,
    current_user: AdminUser,
    service: Annotated[ClientsService, Depends(get_clients_service)],
) -> Response:
    try:
        await service.remove_assignment(
            accountant_id=accountant_id,
            client_id=client_id,
            current_user=current_user,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
