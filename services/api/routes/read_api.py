"""Read-only, display-safe ARC API routes for the operator frontend."""

from dataclasses import asdict
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arc.db.session import get_db_session
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    FailureCategory,
    ProviderMode,
)
from arc.outcomes import calculate_recovery_metrics
from arc.evaluation.read_model import (
    EvaluationSummaryUnavailableError,
    load_evaluation_summary,
)
from arc.read_models import (
    ApprovalQueueItem,
    CaseDetail,
    CaseListItem,
    DashboardSummary,
    EvaluationSummary,
    RecoveryActionItem,
    TimelineItem,
    get_case_detail,
    get_case_timeline,
    list_approval_queue,
    list_case_summaries,
    list_recovery_actions,
)

router = APIRouter(prefix="/api/v1", tags=["read-api"])

DbSession = Annotated[Session, Depends(get_db_session)]


@router.get("/evaluation/summary", response_model=EvaluationSummary)
def evaluation_summary() -> EvaluationSummary:
    """Return the validated aggregate synthetic-evaluation artifact."""

    try:
        return load_evaluation_summary()
    except EvaluationSummaryUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "EVALUATION_SUMMARY_UNAVAILABLE",
                "message": "Evaluation summary is unavailable",
            },
        ) from None


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    session: DbSession,
    provider_mode: str = "TEST",
    currency: str = "INR",
) -> DashboardSummary:
    """Return evidence-backed metrics scoped to one mode and currency."""

    mode = _enum_filter(ProviderMode, provider_mode, "provider_mode")
    normalized_currency = _currency_filter(currency)
    try:
        metrics = calculate_recovery_metrics(
            session,
            provider_mode=mode,
            currency=normalized_currency,
        )
        return DashboardSummary(**asdict(metrics))
    except SQLAlchemyError:
        _read_unavailable()


@router.get("/cases", response_model=list[CaseListItem])
def cases(
    session: DbSession,
    state: str | None = None,
    failure_category: str | None = None,
    provider_mode: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[CaseListItem]:
    """List sanitized cases with bounded filters and pagination."""

    state_filter = _optional_enum_filter(CaseState, state, "state")
    failure_filter = _optional_enum_filter(
        FailureCategory,
        failure_category,
        "failure_category",
    )
    mode_filter = _optional_enum_filter(
        ProviderMode,
        provider_mode,
        "provider_mode",
    )
    try:
        return list_case_summaries(
            session,
            state=state_filter,
            failure_category=failure_filter,
            provider_mode=mode_filter,
            limit=limit,
            offset=offset,
        )
    except SQLAlchemyError:
        _read_unavailable()


@router.get("/cases/{case_reference}", response_model=CaseDetail)
def case_detail(case_reference: str, session: DbSession) -> CaseDetail:
    """Return one sanitized case aggregate without provider/customer ids."""

    try:
        detail = get_case_detail(session, case_reference)
    except SQLAlchemyError:
        _read_unavailable()
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": "Case not found"},
        )
    return detail


@router.get(
    "/cases/{case_reference}/timeline",
    response_model=list[TimelineItem],
)
def case_timeline(
    case_reference: str,
    session: DbSession,
) -> list[TimelineItem]:
    """Return a normalized chronological decision and audit trace."""

    try:
        timeline = get_case_timeline(session, case_reference)
    except SQLAlchemyError:
        _read_unavailable()
    if timeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": "Case not found"},
        )
    return timeline


@router.get("/approvals", response_model=list[ApprovalQueueItem])
def approvals(
    session: DbSession,
    approval_status: Annotated[str, Query(alias="status")] = "PENDING",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ApprovalQueueItem]:
    """List approval requests; pending is the fail-safe default view."""

    status_filter = _enum_filter(
        ApprovalStatus,
        approval_status,
        "approval_status",
    )
    try:
        return list_approval_queue(
            session,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except SQLAlchemyError:
        _read_unavailable()


@router.get("/recovery-actions", response_model=list[RecoveryActionItem])
def recovery_actions(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[RecoveryActionItem]:
    """List sanitized governed action outcomes without execution secrets."""

    try:
        return list_recovery_actions(session, limit=limit, offset=offset)
    except SQLAlchemyError:
        _read_unavailable()


def _optional_enum_filter(enum_type, value: str | None, name: str):
    if value is None:
        return None
    return _enum_filter(enum_type, value, name)


def _enum_filter(enum_type, value: str, name: str):
    try:
        return enum_type(value.strip().upper())
    except (AttributeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_FILTER",
                "message": f"Invalid {name} filter",
            },
        ) from None


def _currency_filter(value: str) -> str:
    normalized = value.strip().upper() if isinstance(value, str) else ""
    if len(normalized) != 3 or not normalized.isalpha():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_FILTER",
                "message": "Invalid currency filter",
            },
        )
    return normalized


def _read_unavailable() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "READ_MODEL_UNAVAILABLE",
            "message": "Read model storage is unavailable",
        },
    ) from None
