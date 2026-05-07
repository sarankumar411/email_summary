import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import WriteSessionMaker
from app.modules.clients.models import Client
from app.modules.email_source.models import Email, EmailDirection
from app.modules.identity.models import Accountant


async def main() -> None:
    async with WriteSessionMaker() as session:
        client = await session.scalar(
            select(Client).where(Client.full_name == "Acme Manufacturing")
        )
        accountant = await session.scalar(
            select(Accountant).where(Accountant.email == "alex@ascendcpa.co")
        )
        if client is None or accountant is None:
            raise RuntimeError("Run scripts/seed.py before adding new emails.")

        session.add(
            Email(
                client_id=client.id,
                sender_accountant_id=accountant.id,
                sender_email="alex@ascendcpa.co",
                recipients=["owner@acmemfg.co"],
                cc=[],
                thread_id="acme-open-items",
                subject="Remaining open items",
                body=(
                    "Please provide the fixed asset additions schedule. "
                    "We can complete the depreciation review after that arrives."
                ),
                sent_at=datetime.now(UTC),
                direction=EmailDirection.outbound,
            )
        )
        await session.commit()
    print("Added one new Acme email.")


if __name__ == "__main__":
    asyncio.run(main())
