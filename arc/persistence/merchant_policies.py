"""Persistence operations for merchant policies."""

from sqlalchemy.orm import Session

from arc.domain.models import MerchantPolicy


def create_merchant_policy(
    session: Session,
    merchant_policy: MerchantPolicy,
) -> MerchantPolicy:
    """Persist one merchant policy inside the caller's transaction."""

    session.add(merchant_policy)
    session.flush()
    return merchant_policy
