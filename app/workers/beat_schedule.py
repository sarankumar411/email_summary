import asyncio

from app.db.session import WriteSessionMaker
from app.modules.jobs.service import JobsService
from app.workers.celery_app import celery_app


@celery_app.task(name="jobs.cleanup_expired")
def cleanup_expired_jobs_task() -> int:
    return asyncio.run(_cleanup_expired_jobs())


async def _cleanup_expired_jobs() -> int:
    async with WriteSessionMaker() as session:
        return await JobsService(session).cleanup_expired_jobs()


celery_app.conf.beat_schedule = {
    "cleanup-expired-jobs-hourly": {
        "task": "jobs.cleanup_expired",
        "schedule": 3600.0,
    },
}

