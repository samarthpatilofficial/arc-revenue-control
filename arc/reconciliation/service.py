"""Application service for reconciling persisted webhook signals to current truth."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arc.domain.enums import EventProcessingStatus
from arc.domain.models import WebhookEvent
from arc.integrations.razorpay import (
    PaymentSnapshot,
    RazorpayClientError,
    RazorpayEntityReader,
    SubscriptionSnapshot,
)
from arc.integrations.razorpay.webhook_payload import SUPPORTED_RAZORPAY_EVENTS
from arc.persistence import CasePersistenceError
from arc.reconciliation.errors import (
    WebhookEventNotFoundError,
    WebhookProcessingError,
)
from arc.reconciliation.payment import reconcile_payment
from arc.reconciliation.subscription import reconcile_subscription

MAX_PROCESSING_ERROR_LENGTH = 256


@dataclass(frozen=True, slots=True)
class WebhookProcessingResult:
    """Sanitized outcome from processing one immutable ledger event."""

    event_id: UUID
    processing_status: EventProcessingStatus
    case_id: UUID | None
    reason_code: str
    idempotent: bool = False


@dataclass(frozen=True, slots=True)
class _ClaimedEvent:
    id: UUID
    razorpay_event_id: str
    event_type: str
    account_id: str | None
    payment_id: str | None
    subscription_id: str | None
    customer_id: str | None


class WebhookEventProcessor:
    """Coordinate event lifecycle, external reads, and transactional case updates."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        razorpay_client: RazorpayEntityReader,
    ) -> None:
        self._session_factory = session_factory
        self._razorpay_client = razorpay_client

    def process_webhook_event(self, event_id: UUID) -> WebhookProcessingResult:
        """Process a stored event once without invoking any recovery action."""

        claim = self._claim_event(event_id)
        if isinstance(claim, WebhookProcessingResult):
            return claim

        try:
            snapshot = self._fetch_authoritative_entity(claim)
            return self._apply_reconciliation(claim, snapshot)
        except RazorpayClientError as error:
            return self._mark_failed(claim.id, str(error))
        except (CasePersistenceError, WebhookProcessingError) as error:
            return self._mark_failed(claim.id, str(error))
        except SQLAlchemyError:
            return self._mark_failed(
                claim.id,
                "ARC database reconciliation failed",
            )
        except Exception:
            return self._mark_failed(
                claim.id,
                "Webhook reconciliation failed safely",
            )

    def _claim_event(
        self,
        event_id: UUID,
    ) -> _ClaimedEvent | WebhookProcessingResult:
        with self._session_factory() as session:
            event = session.scalar(
                select(WebhookEvent)
                .where(WebhookEvent.id == event_id)
                .with_for_update()
            )
            if event is None:
                raise WebhookEventNotFoundError("Webhook event was not found")

            if (
                event.processing_status is EventProcessingStatus.UNSUPPORTED
                or event.event_type not in SUPPORTED_RAZORPAY_EVENTS
            ):
                if event.processing_status is not EventProcessingStatus.UNSUPPORTED:
                    event.processing_status = EventProcessingStatus.UNSUPPORTED
                    session.commit()
                return WebhookProcessingResult(
                    event_id=event.id,
                    processing_status=EventProcessingStatus.UNSUPPORTED,
                    case_id=None,
                    reason_code="UNSUPPORTED_EVENT",
                    idempotent=True,
                )

            if event.processing_status is EventProcessingStatus.PROCESSED:
                return WebhookProcessingResult(
                    event_id=event.id,
                    processing_status=EventProcessingStatus.PROCESSED,
                    case_id=None,
                    reason_code="EVENT_ALREADY_PROCESSED",
                    idempotent=True,
                )

            if event.processing_status is EventProcessingStatus.PROCESSING:
                return WebhookProcessingResult(
                    event_id=event.id,
                    processing_status=EventProcessingStatus.PROCESSING,
                    case_id=None,
                    reason_code="EVENT_ALREADY_PROCESSING",
                    idempotent=True,
                )

            event.processing_status = EventProcessingStatus.PROCESSING
            event.processed_at = None
            event.processing_error = None
            claimed = _ClaimedEvent(
                id=event.id,
                razorpay_event_id=event.razorpay_event_id,
                event_type=event.event_type,
                account_id=event.account_id,
                payment_id=event.payment_id,
                subscription_id=event.subscription_id,
                customer_id=event.customer_id,
            )
            session.commit()
            return claimed

    def _fetch_authoritative_entity(
        self,
        event: _ClaimedEvent,
    ) -> PaymentSnapshot | SubscriptionSnapshot:
        if event.event_type.startswith("payment."):
            if event.payment_id is None:
                raise WebhookProcessingError(
                    "Payment webhook is missing a payment identifier"
                )
            return self._razorpay_client.fetch_payment(event.payment_id)

        if event.subscription_id is None:
            raise WebhookProcessingError(
                "Subscription webhook is missing a subscription identifier"
            )
        return self._razorpay_client.fetch_subscription(event.subscription_id)

    def _apply_reconciliation(
        self,
        claimed: _ClaimedEvent,
        snapshot: PaymentSnapshot | SubscriptionSnapshot,
    ) -> WebhookProcessingResult:
        with self._session_factory() as session:
            event = session.scalar(
                select(WebhookEvent)
                .where(WebhookEvent.id == claimed.id)
                .with_for_update()
            )
            if event is None:
                raise WebhookEventNotFoundError("Webhook event was not found")
            if event.processing_status is EventProcessingStatus.PROCESSED:
                return WebhookProcessingResult(
                    event_id=event.id,
                    processing_status=EventProcessingStatus.PROCESSED,
                    case_id=None,
                    reason_code="EVENT_ALREADY_PROCESSED",
                    idempotent=True,
                )
            if event.processing_status is not EventProcessingStatus.PROCESSING:
                raise WebhookProcessingError(
                    "Webhook event is not available for reconciliation"
                )

            if isinstance(snapshot, PaymentSnapshot):
                case_id, reason_code = reconcile_payment(session, event, snapshot)
            else:
                case_id, reason_code = reconcile_subscription(
                    session,
                    event,
                    snapshot,
                )

            event.processing_status = EventProcessingStatus.PROCESSED
            event.processed_at = datetime.now(UTC)
            event.processing_error = None
            session.commit()
            return WebhookProcessingResult(
                event_id=event.id,
                processing_status=EventProcessingStatus.PROCESSED,
                case_id=case_id,
                reason_code=reason_code,
            )

    def _mark_failed(
        self,
        event_id: UUID,
        safe_error: str,
    ) -> WebhookProcessingResult:
        bounded_error = safe_error[:MAX_PROCESSING_ERROR_LENGTH]
        with self._session_factory() as session:
            event = session.scalar(
                select(WebhookEvent)
                .where(WebhookEvent.id == event_id)
                .with_for_update()
            )
            if event is None:
                raise WebhookEventNotFoundError("Webhook event was not found")
            if event.processing_status is EventProcessingStatus.PROCESSED:
                return WebhookProcessingResult(
                    event_id=event.id,
                    processing_status=EventProcessingStatus.PROCESSED,
                    case_id=None,
                    reason_code="EVENT_ALREADY_PROCESSED",
                    idempotent=True,
                )
            event.processing_status = EventProcessingStatus.FAILED
            event.processing_error = bounded_error
            event.processed_at = datetime.now(UTC)
            session.commit()
            return WebhookProcessingResult(
                event_id=event.id,
                processing_status=EventProcessingStatus.FAILED,
                case_id=None,
                reason_code="RECONCILIATION_FAILED",
            )


def process_webhook_event(
    event_id: UUID,
    *,
    session_factory: Callable[[], Session],
    razorpay_client: RazorpayEntityReader,
) -> WebhookProcessingResult:
    """Convenience entry point for direct application-service invocation."""

    return WebhookEventProcessor(
        session_factory=session_factory,
        razorpay_client=razorpay_client,
    ).process_webhook_event(event_id)
