import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import CurrentUser, get_clients_read_service
from app.modules.clients.schemas import ClientListResponse, ClientOut
from app.modules.clients.service import ClientsService

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=ClientListResponse)
async def list_clients(
    current_user: CurrentUser,
    service: Annotated[ClientsService, Depends(get_clients_read_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ClientListResponse:
    return await service.list_clients(current_user, page=page, page_size=page_size)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: uuid.UUID,
    current_user: CurrentUser,
    service: Annotated[ClientsService, Depends(get_clients_read_service)],
) -> ClientOut:
    return await service.get_client_detail(client_id, current_user)

