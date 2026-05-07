from datetime import UTC, datetime
from uuid import uuid4

from app.config import Settings
from app.modules.email_source.interface import EmailMessage
from app.modules.summarization.gemini_client import GeminiClient


async def test_mock_summary_extracts_required_fields() -> None:
    email = EmailMessage(
        id=uuid4(),
        client_id=uuid4(),
        sender_accountant_id=None,
        sender_email="owner@clientmail.co",
        recipients=["alex@firmmail.co"],
        cc=["maya@firmmail.co"],
        thread_id="thread-1",
        subject="Tax notice",
        body="Alex, please send the filing receipt. The notice is resolved and closed.",
        sent_at=datetime.now(UTC),
        direction="inbound",
    )
    client = GeminiClient(Settings(use_mock_gemini=True))

    summary = await client.summarize_emails([email])

    assert any(actor.source == "header" for actor in summary.actors)
    assert any(actor.source == "body" for actor in summary.actors)
    assert summary.open_action_items
    assert summary.concluded_discussions
