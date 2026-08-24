"""Public API for ARC's isolated synthetic batch evaluation."""

from arc.evaluation.models import (
    EvaluationAssessment,
    EvaluationCaseResult,
    EvaluationMetrics,
    EvaluationReport,
    FinalClassification,
    ScenarioKind,
    SyntheticOutcome,
    SyntheticScenario,
)
from arc.evaluation.runner import (
    render_evaluation_report,
    run_batch_evaluation,
    write_evaluation_report,
)
from arc.evaluation.scenarios import (
    DATASET_CASE_COUNT,
    DATASET_SEED,
    DATASET_VERSION,
    generate_scenarios,
    scenario_counts,
)
from arc.evaluation.strategy import (
    OfflineStrategyProvider,
    OpenAIStrategyProvider,
)

__all__ = [
    "DATASET_CASE_COUNT",
    "DATASET_SEED",
    "DATASET_VERSION",
    "EvaluationAssessment",
    "EvaluationCaseResult",
    "EvaluationMetrics",
    "EvaluationReport",
    "FinalClassification",
    "OfflineStrategyProvider",
    "OpenAIStrategyProvider",
    "ScenarioKind",
    "SyntheticOutcome",
    "SyntheticScenario",
    "generate_scenarios",
    "render_evaluation_report",
    "run_batch_evaluation",
    "scenario_counts",
    "write_evaluation_report",
]
