from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.config import Settings
from app.core.auth_context import AuthenticatedUser
from app.core.exceptions import NotFoundError
from app.modules.clients.models import ClientEmail
from app.modules.jobs.models import Job, JobStatus, JobType
from app.modules.jobs.service import JobsService
from app.modules.summarization.gemini_client import GeminiClient
from app.modules.summarization.models import RefreshAuditStatus
from app.modules.summarization.router import refresh_summary
from app.modules.summarization.schemas import GeminiSummarySchema
from app.modules.summarization.service import SummarizationService


def user_context(*, firm_id, role="accountant") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        firm_id=firm_id,
        email="user@example.com",
        full_name="Example User",
        role=role,
        is_active=True,
    )


def make_job(*, client_id, requester_id) -> Job:
    return Job(
        id=uuid4(),
        job_type=JobType.refresh_summary,
        client_id=client_id,
        triggered_by_accountant_id=requester_id,
        status=JobStatus.queued,
        expires_at=datetime.now(UTC),
    )


class FakeJobsRepository:
    def __init__(self, job: Job) -> None:
        self.job = job

    async def get_job(self, job_id):
        return self.job if self.job.id == job_id else None


class FakeClientsService:
    def __init__(self, firm_id) -> None:
        self.firm_id = firm_id

    async def get_client_context(self, client_id):
        return SimpleNamespace(id=client_id, firm_id=self.firm_id)


class FakeIdentityService:
    async def get_accountant_context(self, accountant_id):
        return None


async def test_admin_cannot_read_other_firm_job() -> None:
    admin_firm_id = uuid4()
    other_firm_id = uuid4()
    job = make_job(client_id=uuid4(), requester_id=uuid4())
    service = JobsService.__new__(JobsService)
    service.repository = FakeJobsRepository(job)
    service.clients_service = FakeClientsService(other_firm_id)
    service.identity_service = FakeIdentityService()

    try:
        await service.get_visible_job(job.id, user_context(firm_id=admin_firm_id, role="admin"))
    except NotFoundError:
        return

    raise AssertionError("Expected cross-firm admin job access to be hidden")


async def test_admin_can_read_same_firm_job() -> None:
    firm_id = uuid4()
    job = make_job(client_id=uuid4(), requester_id=uuid4())
    service = JobsService.__new__(JobsService)
    service.repository = FakeJobsRepository(job)
    service.clients_service = FakeClientsService(firm_id)
    service.identity_service = FakeIdentityService()

    visible = await service.get_visible_job(job.id, user_context(firm_id=firm_id, role="admin"))

    assert visible.id == job.id


class FakeRefreshClientsService:
    async def get_accessible_client(self, client_id, user):
        return SimpleNamespace(id=client_id, firm_id=user.firm_id)

    async def get_client_context(self, client_id):
        return SimpleNamespace(id=client_id, firm_id=uuid4())


class FakeRefreshJobsService:
    def __init__(self) -> None:
        self.force: bool | None = None

    async def enqueue_refresh(self, *, client_id, triggered_by, force):
        self.force = force
        return SimpleNamespace(id=uuid4(), status=JobStatus.queued)


async def test_refresh_endpoint_allows_omitted_body() -> None:
    jobs_service = FakeRefreshJobsService()

    response = await refresh_summary(
        uuid4(),
        user_context(firm_id=uuid4()),
        FakeRefreshClientsService(),
        jobs_service,
        None,
    )

    assert response.status == JobStatus.queued
    assert jobs_service.force is False


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeSummaryRepository:
    def __init__(self, summary_id) -> None:
        self.summary = SimpleNamespace(id=summary_id, emails_analyzed_count=0)
        self.audit_rows: list[dict] = []

    async def get_summary_by_client(self, client_id):
        return self.summary

    async def create_audit_log(self, **kwargs):
        self.audit_rows.append(kwargs)


class FailingGeminiClient:
    async def summarize_emails(self, emails):
        raise RuntimeError("gemini unavailable")


class FakeEmailSource:
    async def count_emails_for_client(self, client_id):
        return 1

    async def fetch_emails_for_client(self, client_id):
        return []


class FakeSummaryJobsService:
    def __init__(self) -> None:
        self.completed: dict | None = None

    async def mark_running(self, job_id) -> None:
        return None

    async def mark_completed(self, job_id, **kwargs) -> None:
        self.completed = kwargs


async def no_lock(client_id) -> None:
    return None


async def test_failed_refresh_writes_failed_audit_row() -> None:
    service = SummarizationService.__new__(SummarizationService)
    service.session = FakeSession()
    service.repository = FakeSummaryRepository(summary_id=uuid4())
    service.clients_service = FakeRefreshClientsService()
    service.jobs_service = FakeSummaryJobsService()
    service.email_source = FakeEmailSource()
    service.gemini_client = FailingGeminiClient()
    service.settings = Settings()
    service._acquire_advisory_lock = no_lock

    try:
        await service.refresh_summary(
            job_id=uuid4(),
            client_id=uuid4(),
            triggered_by_accountant_id=uuid4(),
            force=True,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected refresh failure to be re-raised")

    assert service.repository.audit_rows[0]["status"] == RefreshAuditStatus.failed
    assert service.repository.audit_rows[0]["error_message"] == "gemini unavailable"
    assert service.jobs_service.completed["status"] == "failed"


class RecordingGeminiClient(GeminiClient):
    def __init__(self) -> None:
        super().__init__(Settings(use_mock_gemini=False, gemini_api_key="test-key"))
        self.prompt: str | None = None

    async def _call_gemini_with_prompt(self, prompt: str) -> GeminiSummarySchema:
        self.prompt = prompt
        return GeminiSummarySchema(actors=[], concluded_discussions=[], open_action_items=[])


async def test_real_merge_uses_final_gemini_reduce_call() -> None:
    client = RecordingGeminiClient()
    partial = GeminiSummarySchema(actors=[], concluded_discussions=[], open_action_items=[])

    await client.merge_summaries([partial])

    assert client.prompt is not None
    assert "Partial summaries" in client.prompt


def test_client_email_schema_enforces_firm_email_uniqueness() -> None:
    constraint_names = {constraint.name for constraint in ClientEmail.__table__.constraints}

    assert "created_at" in ClientEmail.__table__.columns
    assert "firm_id" in ClientEmail.__table__.columns
    assert "uq_client_emails_firm_email" in constraint_names
