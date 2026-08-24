"""PostgreSQL proof that synthetic evaluation cannot alter operational data."""

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from arc.domain.enums import ProviderMode
from arc.evaluation import run_batch_evaluation
from arc.outcomes.queries import calculate_recovery_metrics

OPERATIONAL_TABLES = (
    "webhook_events",
    "payment_cases",
    "case_events",
    "strategy_proposals",
    "policy_decisions",
    "approval_requests",
    "recovery_actions",
    "recovery_outcome_observations",
    "recovery_attributions",
)


def test_offline_evaluation_does_not_mutate_operational_rows_or_metrics(
    db_session: Session,
) -> None:
    before_counts = _row_counts(db_session)
    before_test = asdict(
        calculate_recovery_metrics(
            db_session,
            provider_mode=ProviderMode.TEST,
            currency="INR",
        )
    )
    before_live = asdict(
        calculate_recovery_metrics(
            db_session,
            provider_mode=ProviderMode.LIVE,
            currency="INR",
        )
    )

    report = run_batch_evaluation()

    assert report.assessment.passed is True
    assert _row_counts(db_session) == before_counts
    assert asdict(
        calculate_recovery_metrics(
            db_session,
            provider_mode=ProviderMode.TEST,
            currency="INR",
        )
    ) == before_test
    assert asdict(
        calculate_recovery_metrics(
            db_session,
            provider_mode=ProviderMode.LIVE,
            currency="INR",
        )
    ) == before_live


def _row_counts(session: Session) -> dict[str, int]:
    return {
        table: session.execute(
            text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one()
        for table in OPERATIONAL_TABLES
    }
