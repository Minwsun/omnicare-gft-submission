from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolRisk = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ApprovalMode = Literal["NONE", "CUSTOMER_CONFIRMATION", "HUMAN_APPROVAL"]


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    approval: ApprovalMode
    reason: str


def evaluate_tool_policy(
    *,
    operation: str,
    risk: ToolRisk,
    allowed_roles: frozenset[str],
    actor_role: str,
    customer_verified: bool,
    approval: ApprovalMode,
) -> ToolPolicyDecision:
    if actor_role not in allowed_roles:
        return ToolPolicyDecision(False, approval, "ROLE_NOT_ALLOWED")
    if operation == "WRITE" and actor_role == "CUSTOMER" and not customer_verified:
        return ToolPolicyDecision(False, approval, "CUSTOMER_CONTEXT_REQUIRED")
    if operation == "WRITE" and risk in {"HIGH", "CRITICAL"} and approval == "NONE":
        return ToolPolicyDecision(False, "HUMAN_APPROVAL", "HIGH_RISK_APPROVAL_REQUIRED")
    return ToolPolicyDecision(True, approval, "ALLOWED")
