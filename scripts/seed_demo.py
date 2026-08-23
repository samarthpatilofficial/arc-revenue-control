"""Seed controlled offline demo scenarios when explicitly enabled."""

from arc.demo import DemoModeDisabledError, seed_demo_scenarios


def main() -> int:
    try:
        result = seed_demo_scenarios()
    except DemoModeDisabledError as error:
        print(str(error))
        return 2
    print(
        f"Demo scenarios ready: {len(result.scenarios)} "
        f"({result.created_count} newly created)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
