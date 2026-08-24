"""Run ARC's isolated synthetic batch evaluation."""

import argparse
from pathlib import Path

from arc.config import get_settings
from arc.evaluation import (
    OpenAIStrategyProvider,
    generate_scenarios,
    render_evaluation_report,
    run_batch_evaluation,
    write_evaluation_report,
)
from arc.integrations.openai import OpenAIResponsesClient

DEFAULT_RESULT_PATH = Path("evaluation/results/latest.json")


def main() -> int:
    """Execute one bounded evaluation and return a safety-aware exit code."""

    parser = _parser()
    arguments = parser.parse_args()
    scenarios = generate_scenarios()
    limit = arguments.limit
    if arguments.strategy_mode == "openai" and limit is None:
        limit = 20
    if limit is not None:
        scenarios = scenarios[:limit]

    provider: OpenAIStrategyProvider | None = None
    if arguments.strategy_mode == "openai":
        settings = get_settings()
        api_key = settings.openai_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            parser.error("OpenAI strategy credentials are not configured")
        provider = OpenAIStrategyProvider(
            OpenAIResponsesClient(
                api_key=api_key,
                model=settings.openai_model,
                base_url=settings.openai_api_base_url,
            )
        )

    report = run_batch_evaluation(
        scenarios=scenarios,
        strategy_provider=provider,
    )
    output_path = arguments.output
    if (
        output_path is None
        and arguments.strategy_mode == "offline"
        and limit is None
    ):
        output_path = DEFAULT_RESULT_PATH
    if output_path is not None:
        write_evaluation_report(report, output_path)
    print(render_evaluation_report(report))
    return 0 if report.assessment.passed else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate ARC against isolated, deterministic synthetic cases."
        )
    )
    parser.add_argument(
        "--strategy-mode",
        choices=("offline", "openai"),
        default="offline",
        help=(
            "Use deterministic fixtures (default) or the configured OpenAI "
            "strategy boundary. Neither mode calls Razorpay."
        ),
    )
    parser.add_argument(
        "--limit",
        type=_positive_limit,
        help=(
            "Evaluate the first N deterministic cases (maximum 100). OpenAI "
            "mode defaults to 20."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Write an aggregate JSON report. Offline mode defaults to "
            "evaluation/results/latest.json."
        ),
    )
    return parser


def _positive_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 100:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
