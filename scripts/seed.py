import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import WriteSessionMaker
from app.modules.clients.models import AccountantClientAssignment, Client, ClientEmail
from app.modules.email_source.models import Email, EmailDirection
from app.modules.identity.models import Accountant, Firm, Role


async def main() -> None:
    async with WriteSessionMaker() as session:
        existing = await session.scalar(
            select(Accountant).where(Accountant.email == "admin@ascendcpa.co")
        )
        if existing is not None:
            print("Seed data already exists.")
            return

        ascend = Firm(name="Ascend CPA")
        northstar = Firm(name="Northstar Tax")
        session.add_all([ascend, northstar])
        await session.flush()

        password = hash_password("password123")
        admin = Accountant(
            firm_id=ascend.id,
            email="admin@ascendcpa.co",
            full_name="Priya Sharma",
            password_hash=password,
            role=Role.admin,
        )
        accountant = Accountant(
            firm_id=ascend.id,
            email="alex@ascendcpa.co",
            full_name="Alex Rivera",
            password_hash=password,
            role=Role.accountant,
        )
        teammate = Accountant(
            firm_id=ascend.id,
            email="maya@ascendcpa.co",
            full_name="Maya Chen",
            password_hash=password,
            role=Role.accountant,
        )
        superuser = Accountant(
            firm_id=northstar.id,
            email="superuser@platformmail.co",
            full_name="Sam Platform",
            password_hash=password,
            role=Role.superuser,
        )
        session.add_all([admin, accountant, teammate, superuser])
        await session.flush()

        acme = Client(firm_id=ascend.id, full_name="Acme Manufacturing")
        bright = Client(firm_id=ascend.id, full_name="Bright Dental Group")
        orbit = Client(firm_id=northstar.id, full_name="Orbit Retail")
        session.add_all([acme, bright, orbit])
        await session.flush()

        session.add_all(
            [
                ClientEmail(
                    firm_id=ascend.id,
                    client_id=acme.id,
                    email_address="owner@acmemfg.co",
                    is_primary=True,
                ),
                ClientEmail(
                    firm_id=ascend.id,
                    client_id=acme.id,
                    email_address="ap@acmemfg.co",
                    is_primary=False,
                ),
                ClientEmail(
                    firm_id=ascend.id,
                    client_id=bright.id,
                    email_address="finance@brightdental.co",
                    is_primary=True,
                ),
                ClientEmail(
                    firm_id=northstar.id,
                    client_id=orbit.id,
                    email_address="controller@orbitretail.co",
                    is_primary=True,
                ),
                AccountantClientAssignment(accountant_id=accountant.id, client_id=acme.id),
                AccountantClientAssignment(accountant_id=teammate.id, client_id=acme.id),
                AccountantClientAssignment(accountant_id=teammate.id, client_id=bright.id),
            ]
        )

        base = datetime.now(UTC) - timedelta(days=12)
        session.add_all(
            [
                Email(
                    client_id=acme.id,
                    sender_accountant_id=accountant.id,
                    sender_email="alex@ascendcpa.co",
                    recipients=["owner@acmemfg.co"],
                    cc=["maya@ascendcpa.co"],
                    thread_id="acme-2025-tax-docs",
                    subject="2025 tax document checklist",
                    body=(
                        "Hi Anita, please send the March bank statements and payroll register. "
                        "Maya is copied so she can reconcile the W-2 totals."
                    ),
                    sent_at=base,
                    direction=EmailDirection.outbound,
                ),
                Email(
                    client_id=acme.id,
                    sender_accountant_id=None,
                    sender_email="owner@acmemfg.co",
                    recipients=["alex@ascendcpa.co"],
                    cc=["ap@acmemfg.co"],
                    thread_id="acme-2025-tax-docs",
                    subject="2025 tax document checklist",
                    body=(
                        "Alex, I uploaded the March bank statements. We still need AP to provide "
                        "the payroll register by Friday."
                    ),
                    sent_at=base + timedelta(days=1),
                    direction=EmailDirection.inbound,
                ),
                Email(
                    client_id=acme.id,
                    sender_accountant_id=teammate.id,
                    sender_email="maya@ascendcpa.co",
                    recipients=["owner@acmemfg.co"],
                    cc=["alex@ascendcpa.co"],
                    thread_id="acme-sales-tax",
                    subject="Sales tax notice",
                    body=(
                        "The sales tax notice is resolved. Anita confirmed the state accepted the "
                        "amended filing and closed the case."
                    ),
                    sent_at=base + timedelta(days=3),
                    direction=EmailDirection.outbound,
                ),
                Email(
                    client_id=bright.id,
                    sender_accountant_id=teammate.id,
                    sender_email="maya@ascendcpa.co",
                    recipients=["finance@brightdental.co"],
                    cc=[],
                    thread_id="bright-qbo-access",
                    subject="QuickBooks access",
                    body="Please grant accountant access to QuickBooks so we can close April.",
                    sent_at=base + timedelta(days=4),
                    direction=EmailDirection.outbound,
                ),
            ]
        )

        await session.commit()

    print("Seed complete.")
    print("Logins:")
    print("  admin@ascendcpa.co / password123")
    print("  alex@ascendcpa.co / password123")
    print("  maya@ascendcpa.co / password123")
    print("  superuser@platformmail.co / password123")


if __name__ == "__main__":
    asyncio.run(main())
