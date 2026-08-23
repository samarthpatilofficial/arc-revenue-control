"""Sanitized governed execution failures."""


class RecoveryExecutionError(RuntimeError):
    """Base safe executor error."""

    reason_code = "RECOVERY_EXECUTION_FAILED"


class ExecutionCaseNotFoundError(RecoveryExecutionError, LookupError):
    reason_code = "EXECUTION_CASE_NOT_FOUND"


class ExecutionNotPermittedError(RecoveryExecutionError):
    reason_code = "EXECUTION_NOT_PERMITTED"


class ExecutionRequiresPolicyReevaluationError(RecoveryExecutionError):
    reason_code = "EXECUTION_REQUIRES_POLICY_REEVALUATION"


class ExecutionConfigurationError(RecoveryExecutionError):
    reason_code = "EXECUTION_CONFIGURATION_ERROR"
