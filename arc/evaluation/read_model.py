"""Validated read boundary for the tracked aggregate evaluation artifact."""

import json
from pathlib import Path

from pydantic import ValidationError

from arc.read_models.schemas import EvaluationSummary

DEFAULT_EVALUATION_RESULT_PATH = (
    Path(__file__).resolve().parents[2] / "evaluation" / "results" / "latest.json"
)


class EvaluationSummaryUnavailableError(RuntimeError):
    """Raised when the tracked public aggregate cannot be safely validated."""


def load_evaluation_summary(
    path: Path = DEFAULT_EVALUATION_RESULT_PATH,
) -> EvaluationSummary:
    """Load only the bounded public aggregate fields from the tracked artifact."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        public_payload = {
            "evaluation_name": payload.get("evaluation_name"),
            "evaluation_version": payload.get("evaluation_version"),
            "dataset_version": payload.get("dataset_version"),
            "evidence_class": payload.get("evidence_class"),
            "strategy_mode": payload.get("strategy_mode"),
            "status": payload.get("status"),
            "case_count": payload.get("case_count"),
            "metrics": payload.get("metrics"),
        }
        return EvaluationSummary.model_validate(public_payload)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise EvaluationSummaryUnavailableError(
            "Evaluation summary is unavailable"
        ) from error


__all__ = [
    "DEFAULT_EVALUATION_RESULT_PATH",
    "EvaluationSummaryUnavailableError",
    "load_evaluation_summary",
]
