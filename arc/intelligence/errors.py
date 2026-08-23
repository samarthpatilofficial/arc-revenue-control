"""Sanitized strategy-generation failures safe for audit and operators."""


class StrategyError(RuntimeError):
    """Base class for bounded, non-sensitive strategy failures."""

    reason_code = "STRATEGY_ERROR"


class StrategyConfigurationError(StrategyError):
    """Raised when strategy generation is not configured."""

    reason_code = "STRATEGY_CONFIGURATION_ERROR"


class StrategyAuthenticationError(StrategyError):
    """Raised when the configured provider credentials are rejected."""

    reason_code = "STRATEGY_AUTHENTICATION_FAILED"


class StrategyRateLimitError(StrategyError):
    """Raised when the model provider rejects work due to a bounded limit."""

    reason_code = "STRATEGY_RATE_LIMITED"


class StrategyUnavailableError(StrategyError):
    """Raised when the model provider cannot safely serve the request."""

    reason_code = "STRATEGY_PROVIDER_UNAVAILABLE"


class StrategyInvalidOutputError(StrategyError):
    """Raised when a provider response cannot satisfy the local contract."""

    reason_code = "STRATEGY_INVALID_OUTPUT"


class StrategyRefusalError(StrategyError):
    """Raised when the model refuses the strategy request."""

    reason_code = "STRATEGY_MODEL_REFUSED"


class StrategyNotAllowedError(StrategyError):
    """Raised when deterministic preconditions reject strategy generation."""

    reason_code = "STRATEGY_NOT_ALLOWED"


class StrategyStaleContextError(StrategyError):
    """Raised when model output was generated from superseded case truth."""

    reason_code = "STRATEGY_DISCARDED_STALE_CONTEXT"
