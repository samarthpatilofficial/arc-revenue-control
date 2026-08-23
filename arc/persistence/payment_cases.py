"""Persistence operations for payment cases."""

from sqlalchemy.orm import Session

from arc.domain.models import PaymentCase


def create_payment_case(session: Session, payment_case: PaymentCase) -> PaymentCase:
    """Persist a new payment case inside the caller's transaction."""

    session.add(payment_case)
    session.flush()
    return payment_case
