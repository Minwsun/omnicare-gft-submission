from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .advisor import CasePlan


ModelProfile = Literal["fast", "reasoning", "reviewer"]


class ModelRoutingDecision(BaseModel):
    profile: ModelProfile
    reasons: list[str] = Field(default_factory=list)
    complexity_score: int = Field(default=0, ge=0, le=100)
    escalation_allowed: bool = True


REASONING_INTENTS = {
    "ACCOUNT_SECURITY", "FRAUD_WARNING", "PRIVACY", "REFUND_POLICY",
    "RETURN_POLICY", "PAYMENT_POLICY", "SHIPPING_POLICY",
}


def select_model_profile(
    intent: str,
    plan: CasePlan,
    secondary_intents: list[str] | None = None,
    risk_flags: list[str] | None = None,
    conflicts: list[str] | None = None,
    route_confidence: float = 1,
) -> ModelRoutingDecision:
    reasons: list[str] = []
    score = 0
    if plan.complexity == "MODERATE":
        score += 20
    elif plan.complexity == "COMPLEX":
        score += 40
        reasons.append("COMPLEX_CASE")
    elif plan.complexity == "HIGH_RISK":
        score += 70
        reasons.append("HIGH_RISK_CASE")
    if intent in REASONING_INTENTS:
        score += 35
        reasons.append("AUTHORITATIVE_REASONING")
    if secondary_intents:
        score += min(20, len(secondary_intents) * 10)
        reasons.append("MULTI_INTENT")
    if risk_flags:
        score += min(30, len(risk_flags) * 15)
        reasons.append("RISK_FLAGS")
    if conflicts:
        score += 40
        reasons.append("EVIDENCE_CONFLICT")
    if route_confidence < 0.75:
        score += 25
        reasons.append("LOW_ROUTE_CONFIDENCE")
    score = min(score, 100)
    return ModelRoutingDecision(
        profile="reasoning" if score >= 45 else "fast",
        reasons=reasons or ["FAST_PATH"],
        complexity_score=score,
        escalation_allowed=True,
    )


def reviewer_profile(errors: list[str]) -> ModelRoutingDecision:
    deterministic_only = {"ORDER_ID_MISMATCH", "INTERNAL_CITATION", "TOOL_POLICY_DENIED"}
    needs_model = bool(errors) and not set(errors).issubset(deterministic_only)
    return ModelRoutingDecision(
        profile="reviewer" if needs_model else "fast",
        reasons=["SEMANTIC_REVIEW"] if needs_model else ["DETERMINISTIC_REVIEW"],
        complexity_score=60 if needs_model else 0,
        escalation_allowed=False,
    )
