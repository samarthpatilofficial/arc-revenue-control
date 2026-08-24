"""Report deterministic ARC demo readiness without mutating persisted state."""

from arc.demo.preflight import render_demo_preflight, run_demo_preflight


def main() -> int:
    result = run_demo_preflight()
    print(render_demo_preflight(result))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
