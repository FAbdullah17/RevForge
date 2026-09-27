"""Pydantic models. Source of truth for JSON store + API."""
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


HypothesisStatus = Literal["Candidate", "Prioritized", "Testing", "Validated", "Rejected", "Inconclusive"]


class Hypothesis(BaseModel):
    id: str
    title: str
    pattern: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    novelty: str = "Unknown"
    novelty_reason: str = ""
    testability: str = "Unknown"
    priority: float = 0.0
    priority_breakdown: dict[str, float] = Field(default_factory=dict)
    status: HypothesisStatus = "Candidate"
    explanation: str = ""
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class Experiment(BaseModel):
    id: str
    hypothesis_id: str
    treatment: dict[str, Any] = Field(default_factory=dict)
    control: dict[str, Any] = Field(default_factory=dict)
    graph8_campaign_id: str = ""
    graph8_sequence_id: str = ""
    status: Literal["draft", "launched", "observed", "evaluated"] = "draft"
    transport: str = ""
    started_at: str = Field(default_factory=utcnow)
    launched_at: str = ""
    ended_at: str = ""


class Result(BaseModel):
    experiment_id: str
    group: Literal["treatment", "control"]
    sent: int = 0
    replies: int = 0
    positive: int = 0
    meetings: int = 0
    rate: float = 0.0
    lift: float = 0.0
    n_small: bool = False
    verdict: Literal["Validated", "Rejected", "Inconclusive"] = "Inconclusive"
    source: Literal["live", "seeded", "simulated"] = "seeded"


class Knowledge(BaseModel):
    id: str
    hypothesis_id: str
    pattern: dict[str, Any] = Field(default_factory=dict)
    verdict: str = "Inconclusive"
    confidence: str = "low"
    validated_at: str = Field(default_factory=utcnow)
    reuse_count: int = 0


class Account(BaseModel):
    """Historical revenue account. Seed + loader source of truth."""

    id: str
    company: str
    industry: str
    employees: int
    region: str
    tech: str
    new_vp_sales: bool
    vp_hire_days_ago: int | None = None
    sdr_openings: int
    intent: Literal["high", "medium", "low"]
    persona_title: str
    outcome: Literal["won", "lost"]
    deal_size: int = 0
    # Hidden test label. Discovery MUST NOT use as a feature.
    is_h17_pattern: bool = False
