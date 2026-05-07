import asyncio
import uuid

from app.db.session import WriteSessionMaker
from app.modules.summarization.service import SummarizationService
from app.workers.celery_app import celery_app


@celery_app.task(name="summaries.refresh_summary")
def refresh_summary_task(
    job_id: str,
    client_id: str,
    triggered_by_accountant_id: str,
    force: bool,
) -> dict:
    return asyncio.run(
        _refresh_summary(
            uuid.UUID(job_id),
            uuid.UUID(client_id),
            uuid.UUID(triggered_by_accountant_id),
            force,
        )
    )


async def _refresh_summary(
    job_id: uuid.UUID,
    client_id: uuid.UUID,
    triggered_by_accountant_id: uuid.UUID,
    force: bool,
) -> dict:
    async with WriteSessionMaker() as session:
        service = SummarizationService(session)
        return await service.refresh_summary(
            job_id=job_id,
            client_id=client_id,
            triggered_by_accountant_id=triggered_by_accountant_id,
            force=force,
        )

