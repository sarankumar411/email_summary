from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path", "status_code"],
)
GEMINI_CALLS_TOTAL = Counter("gemini_calls_total", "Total Gemini calls.")
GEMINI_FAILURES_TOTAL = Counter("gemini_failures_total", "Total Gemini failures.")
CACHE_HITS_TOTAL = Counter("cache_hits_total", "Total cache hits.")
CACHE_MISSES_TOTAL = Counter("cache_misses_total", "Total cache misses.")
REFRESH_JOBS_TOTAL = Counter(
    "refresh_jobs_total",
    "Refresh jobs by final status.",
    ["status"],
)
GEMINI_LATENCY_SECONDS = Histogram("gemini_latency_seconds", "Gemini call latency.")
SUMMARIZATION_DURATION_SECONDS = Histogram(
    "summarization_duration_seconds",
    "Summary refresh duration.",
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        elapsed = perf_counter() - start
        REQUEST_DURATION_SECONDS.labels(
            request.method,
            request.url.path,
            str(response.status_code),
        ).observe(elapsed)
        return response


async def metrics_response() -> StarletteResponse:
    return StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

