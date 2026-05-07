from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.core.cache import CacheService
from app.core.exceptions import AuthorizationError, BusinessRuleError, NotFoundError
from app.core.logging import configure_logging
from app.db.session import ReadSessionMaker
from app.modules.clients.router import router as clients_router
from app.modules.identity.router import limiter
from app.modules.identity.router import router as identity_router
from app.modules.jobs.router import router as jobs_router
from app.modules.reporting.router import router as reporting_router
from app.modules.summarization.router import router as summaries_router
from app.observability.metrics import MetricsMiddleware, metrics_response
from app.observability.middleware import RequestContextMiddleware, SecurityHeadersMiddleware

settings = get_settings()
configure_logging()

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(identity_router, prefix=settings.api_v1_prefix)
app.include_router(clients_router, prefix=settings.api_v1_prefix)
app.include_router(summaries_router, prefix=settings.api_v1_prefix)
app.include_router(jobs_router, prefix=settings.api_v1_prefix)
app.include_router(reporting_router, prefix=settings.api_v1_prefix)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> Response:
    del request, exc
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Resource not found"})


@app.exception_handler(AuthorizationError)
async def authorization_handler(request: Request, exc: AuthorizationError) -> Response:
    del request
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(BusinessRuleError)
async def business_rule_handler(request: Request, exc: BusinessRuleError) -> Response:
    del request
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready() -> dict[str, str]:
    try:
        async with ReadSessionMaker() as session:
            await session.execute(text("select 1"))
        await CacheService().ping()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service dependencies are unavailable",
        ) from exc
    return {"status": "ready"}


@app.get("/metrics", tags=["observability"])
async def metrics() -> Response:
    return await metrics_response()
