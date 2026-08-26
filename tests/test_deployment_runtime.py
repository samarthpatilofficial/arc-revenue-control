"""Tests for the portable container startup contract."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_backend_startup_uses_render_port_with_local_default() -> None:
    script = (PROJECT_ROOT / "scripts" / "start_backend.sh").read_text(
        encoding="utf-8"
    )

    assert '--port "${PORT:-8000}"' in script
    assert "python -m alembic upgrade head" in script
    assert "exec python -m uvicorn" in script
