"""Shared PostgreSQL setup and offline provider fake for Task 8 tests."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from arc.assessment import CaseAssessmentService
from arc.domain.enums import CaseState, RecoveryAction, StrategySource
from arc.domain.models import (
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
    StrategyProposal,
)
from arc.integrations.razorpay.payment_links import (
    PaymentLinkCreateRequest,
    PaymentLinkSnapshot,
)
from arc.policy.service import MerchantAuthorizationService
from arc.reconciliation.state_machine import transition_case
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    load_cases,
    payment_snapshot,
    processor,
    store_event,
)


class StubPaymentLinkGateway:
    """Offline provider fake with hooks for crash and capture races."""

    def __init__(self, *, payment_link_id: str = "plink_arc_test") -> None:
        self.calls: list[tuple[str, str]] = []
        self.requests: list[PaymentLinkCreateRequest] = []
        self.lookup_results: list[PaymentLinkSnapshot] | Exception = []
        self.create_error: BaseException | None = None
        self.cancel_error: BaseException | None = None
        self.on_create: Callable[[], None] | None = None
        self.payment_link_id = payment_link_id

    def lookup_by_reference(
        self,
        reference_id: str,
    ) -> list[PaymentLinkSnapshot]:
        self.calls.append(("lookup", reference_id))
        if isinstance(self.lookup_results, Exception):
            raise self.lookup_results
        return self.lookup_results

    def create(
        self,
        request: PaymentLinkCreateRequest,
    ) -> PaymentLinkSnapshot:
        self.calls.append(("create", request.reference_id))
        self.requests.append(request)
        if self.on_create is not None:
            self.on_create()
        if self.create_error is not None:
            raise self.create_error
        return payment_link_snapshot(
            request=request,
            payment_link_id=self.payment_link_id,
        )

    def cancel(self, payment_link_id: str) -> PaymentLinkSnapshot:
        self.calls.append(("cancel", payment_link_id))
        if self.cancel_error is not None:
            raise self.cancel_error
        request = self.requests[-1]
        return payment_link_snapshot(
            request=request,
            payment_link_id=payment_link_id,
            status="cancelled",
        )

    def fetch_by_id(self, payment_link_id: str) -> PaymentLinkSnapshot:
        self.calls.append(("fetch", payment_link_id))
        if isinstance(self.lookup_results, Exception):
            raise self.lookup_results
        if len(self.lookup_results) != 1:
            raise LookupError("Synthetic Payment Link fetch is unavailable")
        return self.lookup_results[0]


def payment_link_snapshot(
    *,
    request: PaymentLinkCreateRequest,
    payment_link_id: str = "plink_arc_test",
    status: str = "created",
    **overrides: object,
) -> PaymentLinkSnapshot:
    values: dict[str, object] = {
        "id": payment_link_id,
        "reference_id": request.reference_id,
        "amount": request.amount,
        "amount_paid": 0,
        "currency": request.currency,
        "status": status,
        "short_url": "https://rzp.io/i/arc-test",
        "expire_by": request.expire_by,
    }
    values.update(overrides)
    return PaymentLinkSnapshot.model_validate(values)


def prepare_policy_decision(
    session_factory: SessionFactory,
    *,
    payment_id: str,
    action: RecoveryAction,
    amount: int = 25_000,
    policy_overrides: dict[str, object] | None = None,
    re_evaluate_after_seconds: int | None = None,
) -> tuple[PaymentCase, StrategyProposal, PolicyDecision]:
    """Build real reconciled/assessed/policy state without model/network calls."""

    razorpay = StubRazorpayClient()
    razorpay.payments[payment_id] = payment_snapshot(
        payment_id=payment_id,
        status="failed",
        amount=amount,
    )
    event_id = store_event(
        session_factory,
        event_type="payment.failed",
        payment_id=payment_id,
    )
    processor(session_factory, razorpay).process_webhook_event(event_id)
    with session_factory() as session:
        payment_case = session.scalar(
            select(PaymentCase).where(PaymentCase.payment_id == payment_id)
        )
        assert payment_case is not None
        session.expunge(payment_case)
    assert payment_case.last_reconciled_at is not None
    assessed_at = payment_case.last_reconciled_at + timedelta(seconds=1)
    CaseAssessmentService(
        session_factory=session_factory,
        clock=lambda: assessed_at,
    ).assess_case(payment_case.id)

    fingerprint = hashlib.sha256(
        f"{payment_id}:{action.value}".encode()
    ).hexdigest()
    with session_factory() as session:
        current = session.get(PaymentCase, payment_case.id)
        assert current is not None
        assert current.assessment_fingerprint is not None
        proposal = StrategyProposal(
            case_id=current.id,
            assessment_fingerprint=current.assessment_fingerprint,
            strategy_input_fingerprint=fingerprint,
            source=StrategySource.RULE,
            action=action,
            reason_code="SYNTHETIC_EXECUTION_TEST",
            explanation="Synthetic bounded execution test proposal.",
            confidence=None,
            re_evaluate_after_seconds=re_evaluate_after_seconds,
            prompt_version="task8-test-v1",
            model=None,
            provider_response_id=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            latency_ms=None,
        )
        session.add(proposal)
        session.flush()
        transition_case(
            session,
            current,
            CaseState.DECISIONED,
            reason_code="SYNTHETIC_STRATEGY_ACCEPTED",
            source="TEST_SETUP",
        )
        session.commit()
        proposal_id = proposal.id
        merchant_id = current.merchant_id

    policy_values: dict[str, object] = {
        "merchant_id": merchant_id,
        "automation_enabled": True,
        "allowed_actions": [
            RecoveryAction.REQUEST_RETRY.value,
            RecoveryAction.CREATE_RECOVERY_LINK.value,
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE.value,
        ],
        "max_automated_attempts": 3,
        "max_contact_attempts": 3,
        "recovery_window_minutes": 60,
        "high_value_threshold_minor": 50_000,
        "require_approval_above_minor": 100_000,
        "stopping_rules": {},
    }
    policy_values.update(policy_overrides or {})
    with session_factory() as session:
        existing_policy = session.scalar(
            select(MerchantPolicy).where(
                MerchantPolicy.merchant_id == merchant_id
            )
        )
        if existing_policy is None:
            session.add(MerchantPolicy(**policy_values))
        session.commit()

    MerchantAuthorizationService(
        session_factory=session_factory,
        clock=lambda: assessed_at + timedelta(seconds=1),
    ).evaluate_policy(
        payment_case.id,
        strategy_proposal_id=proposal_id,
    )
    with session_factory() as session:
        stored_case = session.get(PaymentCase, payment_case.id)
        stored_proposal = session.get(StrategyProposal, proposal_id)
        decision = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.case_id == payment_case.id,
                PolicyDecision.superseded_at.is_(None),
            )
        )
        assert stored_case is not None
        assert stored_proposal is not None
        assert decision is not None
        session.expunge(stored_case)
        session.expunge(stored_proposal)
        session.expunge(decision)
        return stored_case, stored_proposal, decision
