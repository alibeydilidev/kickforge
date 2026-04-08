"""KickForge exceptions."""

from __future__ import annotations


class KickForgeError(Exception):
    """Base exception for all KickForge errors."""


class AuthenticationError(KickForgeError):
    """Raised when OAuth authentication fails."""


class TokenExpiredError(AuthenticationError):
    """Raised when a token has expired and cannot be refreshed."""


class APIError(KickForgeError):
    """Raised when a Kick API call fails."""

    def __init__(self, status_code: int, detail: str, endpoint: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        self.endpoint = endpoint
        super().__init__(f"Kick API error {status_code} on {endpoint}: {detail}")


class RateLimitError(APIError):
    """Raised when hitting Kick API rate limits."""

    def __init__(self, retry_after: float = 0.0, endpoint: str = "") -> None:
        self.retry_after = retry_after
        super().__init__(429, f"Rate limited, retry after {retry_after}s", endpoint)


class WebhookVerificationError(KickForgeError):
    """Raised when webhook signature verification fails."""


class ConfigurationError(KickForgeError):
    """Raised for invalid configuration."""
