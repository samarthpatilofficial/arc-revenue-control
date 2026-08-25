"""Read-only semantic verification of a public evaluator database."""

from arc.deployment import (
    render_public_demo_verification,
    verify_public_demo_database,
)


def main() -> int:
    result = verify_public_demo_database()
    print(render_public_demo_verification(result))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
