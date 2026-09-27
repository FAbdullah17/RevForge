"""Single LLM boundary. Mock-first, one call per stage max.

Pattern: structured analysis first, LLM second for narrative only.
The mock path is deterministic so demos and tests never depend on keys.
"""
from __future__ import annotations

from .config import MOCK_LLM


def explain_pattern(title: str, pattern: dict, evidence: dict) -> str:
    """One-sentence narrative for a discovered pattern.

    Args:
        title: Human-readable pattern name.
        pattern: Conjunction of business attributes.
        evidence: Dict with wins/support/rate/baseline/lift.

    Returns:
        Narrative string. Mock template when MOCK_LLM=1 or no key;
        real-provider call lands here (same signature).
    """
    lift = evidence.get("lift", 0)
    rate = evidence.get("rate", 0)
    baseline = evidence.get("baseline", 0)
    n = evidence.get("support", 0)
    wins = evidence.get("wins", 0)
    if MOCK_LLM:
        return (
            f"{title}: {wins}/{n} wins ({rate:.1%} vs {baseline:.1%} baseline, "
            f"{lift:.2f}x lift). Candidate for a controlled graph8 experiment."
        )
    raise NotImplementedError("Live LLM path is not configured; set MOCK_LLM=1")


# Legacy alias. Prefer explain_pattern().
def explain(pattern: dict, evidence: dict) -> str:
    """Legacy alias. Prefer explain_pattern()."""
    return explain_pattern("Pattern", pattern, evidence)
