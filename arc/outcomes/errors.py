"""Sanitized failures for authoritative recovery observation."""


class RecoveryObservationError(RuntimeError):
    """Base observer failure with no raw provider data."""

    reason_code = "RECOVERY_OBSERVATION_FAILED"


class RecoveryObservationNotFoundError(RecoveryObservationError, LookupError):
    reason_code = "RECOVERY_ACTION_NOT_FOUND"


class RecoveryObservationConfigurationError(RecoveryObservationError):
    reason_code = "RECOVERY_OBSERVATION_CONFIGURATION_ERROR"


class RecoveryObservationProviderError(RecoveryObservationError):
    reason_code = "RECOVERY_PROVIDER_READ_FAILED"
