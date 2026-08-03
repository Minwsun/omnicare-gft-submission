from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    capability: str
    specialist: str
    summary: str
    procedure: tuple[str, ...]
    required_tools: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    risk: str = "LOW"
    version: str = "1.0.0"
    status: Literal["CANDIDATE", "CANARY", "ACTIVE", "DISABLED"] = "ACTIVE"
    success_rate: float = 1
    evaluation_cases: int = 0


class SkillRegistry:
    def __init__(self, skills: tuple[SkillDefinition, ...]) -> None:
        self._skills = list(skills)

    def metadata(self) -> list[dict[str, str]]:
        return [{"name": item.name, "capability": item.capability, "summary": item.summary, "version": item.version} for item in self._skills]

    def select(self, capabilities: set[str], specialists: set[str], limit: int = 4) -> list[SkillDefinition]:
        matches = [item for item in self._skills if item.status in {"CANARY", "ACTIVE"} and item.capability in capabilities and item.specialist in specialists]
        return matches[:limit]

    def propose(self, skill: SkillDefinition, allowed_tools: set[str]) -> SkillDefinition:
        if not set(skill.required_tools).issubset(allowed_tools):
            raise ValueError("SKILL_CANNOT_GRANT_TOOL_PERMISSION")
        candidate = replace(skill, status="CANDIDATE", success_rate=0, evaluation_cases=0)
        self._skills.append(candidate)
        return candidate

    def evaluate(self, name: str, passed: int, total: int) -> SkillDefinition:
        if total < 10 or passed < 0 or passed > total:
            raise ValueError("INVALID_SKILL_EVALUATION")
        current = self._find(name)
        success_rate = passed / total
        status = "CANARY" if success_rate >= 0.9 else "DISABLED"
        return self._replace(replace(current, status=status, success_rate=success_rate, evaluation_cases=total))

    def promote(self, name: str) -> SkillDefinition:
        current = self._find(name)
        if current.status != "CANARY" or current.evaluation_cases < 20 or current.success_rate < 0.95:
            raise ValueError("SKILL_PROMOTION_THRESHOLD_NOT_MET")
        return self._replace(replace(current, status="ACTIVE"))

    def disable(self, name: str) -> SkillDefinition:
        return self._replace(replace(self._find(name), status="DISABLED"))

    def _find(self, name: str) -> SkillDefinition:
        for item in reversed(self._skills):
            if item.name == name:
                return item
        raise KeyError(name)

    def _replace(self, skill: SkillDefinition) -> SkillDefinition:
        index = max(index for index, item in enumerate(self._skills) if item.name == skill.name)
        self._skills[index] = skill
        return skill


skill_registry = SkillRegistry((
    SkillDefinition("resolve-order-context", "ORDER", "order", "Resolve the owned order before answering.", ("Use active order context when present.", "Otherwise list recent eligible orders.", "Verify ownership before exposing details."), ("get_recent_orders", "get_order_details"), ("OWNERSHIP_VERIFIED",)),
    SkillDefinition("track-shipment", "SHIPPING", "logistics", "Explain current shipment state and next useful step.", ("Read order and shipment.", "Translate status and dates naturally.", "Offer investigation only when eligible."), ("get_order_details", "get_shipping_status"), ("SHIPMENT_FRESH",)),
    SkillDefinition("assess-return", "RETURN", "payment_refund", "Assess return eligibility using transaction facts and active policy.", ("Read order items.", "Check eligibility tool.", "Retrieve active return policy.", "Explain reason and available action."), ("get_order_details", "check_return_eligibility", "search_knowledge"), ("ACTIVE_POLICY", "ORDER_OWNED")),
    SkillDefinition("ground-policy-answer", "POLICY", "policy", "Answer policy questions only from active public evidence.", ("Retrieve scoped policy.", "Reject expired or internal evidence.", "Cite the active version."), ("search_knowledge",), ("CITATION_ACTIVE",)),
    SkillDefinition("safe-commerce-action", "CHECKOUT", "product_checkout", "Prepare commerce actions without committing before confirmation.", ("Resolve product and quantity.", "Load owned addresses.", "Create quote.", "Return confirmation interaction."), ("get_product_details", "get_customer_addresses", "quote_checkout"), ("CUSTOMER_CONFIRMED",), "MEDIUM"),
))
