class DomainError(Exception):
    """Base exception for expected domain failures."""


class NotFoundError(DomainError):
    """Resource was not found or is intentionally hidden from the caller."""


class AuthorizationError(DomainError):
    """Caller is authenticated but not permitted to perform the action."""


class ExternalServiceError(DomainError):
    """An upstream service failed after retries were exhausted."""


class BusinessRuleError(DomainError):
    """The request is valid but violates a business rule."""

