"""Bounded strategy-domain contracts, validation, and safe failures."""

from arc.intelligence.errors import (
    StrategyAuthenticationError,
    StrategyConfigurationError,
    StrategyError,
    StrategyInvalidOutputError,
    StrategyNotAllowedError,
    StrategyRateLimitError,
    StrategyRefusalError,
    StrategyStaleContextError,
    StrategyUnavailableError,
)
from arc.intelligence.schemas import StrategyContext, StrategyOutput

__all__ = [
    "StrategyAuthenticationError",
    "StrategyConfigurationError",
    "StrategyContext",
    "StrategyError",
    "StrategyInvalidOutputError",
    "StrategyNotAllowedError",
    "StrategyOutput",
    "StrategyRateLimitError",
    "StrategyRefusalError",
    "StrategyStaleContextError",
    "StrategyUnavailableError",
]
