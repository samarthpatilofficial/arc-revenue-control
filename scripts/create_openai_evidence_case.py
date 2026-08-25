"""Explicit operator entry point for safe OpenAI strategy evidence."""

from arc.demo.openai_evidence import OpenAIEvidenceError, create_openai_evidence_case
from arc.intelligence.errors import StrategyError


def main() -> int:
    """Run once, print only bounded evidence, and never execute recovery."""

    try:
        result = create_openai_evidence_case()
    except (OpenAIEvidenceError, StrategyError) as error:
        reason = getattr(error, "reason_code", "OPENAI_EVIDENCE_FAILED")
        print(f"Failure reason: {reason}")
        print("OPENAI EVIDENCE STATUS: FAIL")
        return 1
    except Exception:
        print("Failure reason: OPENAI_EVIDENCE_FAILED")
        print("OPENAI EVIDENCE STATUS: FAIL")
        return 1

    print(f"Case reference: {result.case_reference}")
    print("Strategy provider: OpenAI")
    print(f"Model: {result.model}")
    print(f"Bounded action: {result.action.value}")
    print(f"Confidence: {result.confidence:.3f}")
    print(f"Policy result: {result.policy_result.value}")
    print(f"Final state: {result.final_state.value}")
    print("Execution: NOT PERFORMED")
    print("Recovery attribution: NONE")
    print("OPENAI EVIDENCE STATUS: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
