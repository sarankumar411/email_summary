from uuid import uuid4

from app.modules.clients.models import Client
from app.modules.clients.service import ClientsService
from app.modules.identity.models import Accountant, Role


class FakeRepository:
    def __init__(self, client: Client, assigned: bool) -> None:
        self.client = client
        self.assigned = assigned

    async def get_client(self, client_id):
        return self.client if self.client.id == client_id else None

    async def is_assigned(self, accountant_id, client_id):
        return self.assigned


async def test_admin_access_is_limited_to_own_firm() -> None:
    firm_id = uuid4()
    other_firm_id = uuid4()
    client = Client(id=uuid4(), firm_id=firm_id, full_name="Acme")
    admin = Accountant(
        id=uuid4(),
        firm_id=other_firm_id,
        email="admin@example.com",
        full_name="Admin",
        password_hash="hash",
        role=Role.admin,
    )
    service = ClientsService.__new__(ClientsService)
    service.repository = FakeRepository(client, assigned=False)

    try:
        await service.get_accessible_client(client.id, admin)
    except Exception as exc:
        assert exc.__class__.__name__ == "NotFoundError"
    else:
        raise AssertionError("Expected NotFoundError")

