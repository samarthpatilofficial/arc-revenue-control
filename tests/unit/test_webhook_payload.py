"""Unit tests for minimal Razorpay webhook envelope normalization."""

from arc.integrations.razorpay import normalize_webhook_payload


def test_payment_entity_subscription_id_is_normalized_for_correlation() -> None:
    normalized = normalize_webhook_payload(
        {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test",
                        "subscription_id": "sub_test",
                    }
                }
            },
        }
    )

    assert normalized.payment_id == "pay_test"
    assert normalized.subscription_id == "sub_test"
