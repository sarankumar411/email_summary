import logging
import sys

import structlog


def configure_logging() -> None:
    """Configure structlog for structured JSON output to stdout.

    Processor chain (applied in order to every log event):
        1. merge_contextvars   — injects request-scoped fields bound via structlog.contextvars
                                  (e.g., request_id bound by RequestContextMiddleware).
        2. add_log_level       — adds a "level" key ("info", "warning", etc.).
        3. TimeStamper         — adds an ISO-8601 UTC "timestamp" key.
        4. JSONRenderer        — serialises the final event dict to a single JSON line.

    Output example:
        {"level":"info","timestamp":"2025-03-20T14:05:32.123Z",
         "request_id":"uuid-1","event":"summary refreshed","client_id":"cli-1"}

    Called once at application startup in app/main.py before any request is served.
    """
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog BoundLogger for use within a module.

    Usage:
        logger = get_logger(__name__)
        logger.info("summary refreshed", client_id=str(client_id), emails=count)
    """
    return structlog.get_logger(name)

