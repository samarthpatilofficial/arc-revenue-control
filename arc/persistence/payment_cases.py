"""Race-safe persistence operations for logical payment cases."""

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arc.domain.models import PaymentCase

CaseIdentityKind = Literal["payment", "subscription"]


@dataclass(frozen=True, slots=True)
class GetOrCreateCaseResult:
    """Outcome of resolving one database-enforced logical case identity."""

    created: bool
    payment_case: PaymentCase


class CasePersistenceError(RuntimeError):
    """Raised when a case insert or conflict cannot be resolved safely."""


def create_payment_case(session: Session, payment_case: PaymentCase) -> PaymentCase:
    """Persist a new payment case inside the caller's transaction."""

    session.add(payment_case)
    session.flush()
    return payment_case


def deterministic_case_reference(
    identity_kind: CaseIdentityKind,
    external_id: str,
) -> str:
    """Return a stable, bounded case key without exposing external identifiers."""

    if not external_id or len(external_id) > 100:
        raise CasePersistenceError("Case identity is missing or invalid")
    digest = hashlib.sha256(
        f"{identity_kind}:{external_id}".encode("utf-8")
    ).hexdigest()[:48]
    prefix = "pay" if identity_kind == "payment" else "sub"
    return f"{prefix}_{digest}"


def lock_case_by_identity(
    session: Session,
    *,
    identity_kind: CaseIdentityKind,
    external_id: str,
) -> PaymentCase | None:
    """Load and row-lock a logical case when it already exists."""

    case_reference = deterministic_case_reference(identity_kind, external_id)
    return session.scalar(
        select(PaymentCase)
        .where(PaymentCase.case_reference == case_reference)
        .with_for_update()
    )


def get_or_create_case(
    session: Session,
    *,
    identity_kind: CaseIdentityKind,
    external_id: str,
    merchant_id: str,
    customer_id: str | None = None,
) -> GetOrCreateCaseResult:
    """Resolve one case using PostgreSQL uniqueness as the race authority."""

    case_reference = deterministic_case_reference(identity_kind, external_id)
    values = {
        "id": uuid4(),
        "case_reference": case_reference,
        "merchant_id": merchant_id,
        "payment_id": external_id if identity_kind == "payment" else None,
        "subscription_id": (
            external_id if identity_kind == "subscription" else None
        ),
        "customer_id": customer_id,
    }
    inserted_id = session.execute(
        insert(PaymentCase)
        .values(**values)
        .on_conflict_do_nothing(
            constraint="uq_payment_cases_case_reference"
        )
        .returning(PaymentCase.id)
    ).scalar_one_or_none()

    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.case_reference == case_reference)
        .with_for_update()
    )
    if payment_case is None:
        raise CasePersistenceError("Payment case could not be resolved")

    return GetOrCreateCaseResult(
        created=inserted_id is not None,
        payment_case=payment_case,
    )
