"""HTTP boundary tests for the evaluator-facing read-only deployment mode."""

import asyncio

from httpx import ASGITransport, AsyncClient

from arc.config import Settings
from services.api.main import create_app


def _settings(*, public_demo_mode: bool) -> Settings:
    return Settings(
        database_url=(
            "postgresql+psycopg://arc:test_only@localhost:5432/arc_test"
        ),
        public_demo_mode=public_demo_mode,
        demo_mode=False,
        razorpay_key_id=None,
        razorpay_key_secret=None,
        razorpay_webhook_secret=None,
        razorpay_webhook_previous_secret=None,
        openai_api_key=None,
        _env_file=None,
    )


def _route_methods(*, public_demo_mode: bool) -> set[tuple[str, str]]:
    app = create_app(_settings(public_demo_mode=public_demo_mode))
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
    }


def test_webhook_is_available_in_normal_mode() -> None:
    assert ("POST", "/webhooks/razorpay") in _route_methods(
        public_demo_mode=False
    )


def test_public_demo_exposes_only_expected_get_boundaries() -> None:
    routes = _route_methods(public_demo_mode=True)
    expected_get_routes = {
        "/health",
        "/ready",
        "/api/v1/dashboard/summary",
        "/api/v1/evaluation/summary",
        "/api/v1/cases",
        "/api/v1/cases/{case_reference}",
        "/api/v1/cases/{case_reference}/timeline",
        "/api/v1/approvals",
        "/api/v1/recovery-actions",
    }

    assert expected_get_routes <= {
        path for method, path in routes if method == "GET"
    }
    assert ("POST", "/webhooks/razorpay") not in routes
    assert not {
        (method, path)
        for method, path in routes
        if method in {"POST", "PUT", "PATCH", "DELETE"}
        and not path.startswith("/openapi")
    }


def test_public_demo_webhook_is_not_found_and_read_api_works() -> None:
    app = create_app(_settings(public_demo_mode=True))

    async def request() -> tuple[int, int]:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            webhook = await client.post("/webhooks/razorpay", content=b"{}")
            evaluation = await client.get("/api/v1/evaluation/summary")
        return webhook.status_code, evaluation.status_code

    webhook_status, evaluation_status = asyncio.run(request())

    assert webhook_status == 404
    assert evaluation_status == 200
