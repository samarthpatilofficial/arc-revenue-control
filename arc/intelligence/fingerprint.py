"""Deterministic strategy input fingerprinting without generated output."""

import hashlib
import json

from arc.intelligence.compatibility import STRATEGY_RULESET_VERSION
from arc.intelligence.prompt import STRATEGY_PROMPT_VERSION
from arc.intelligence.schemas import StrategyContext


def build_strategy_input_fingerprint(
    *,
    assessment_fingerprint: str,
    context: StrategyContext,
    model: str | None,
) -> str:
    """Hash current assessment, strategy configuration, and bounded context."""

    facts = {
        "assessment_fingerprint": assessment_fingerprint,
        "prompt_version": STRATEGY_PROMPT_VERSION,
        "strategy_ruleset_version": STRATEGY_RULESET_VERSION,
        "model": model,
        "context": context.model_dump(mode="json"),
    }
    serialized = json.dumps(
        facts,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
