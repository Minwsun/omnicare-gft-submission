from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistProfile:
    name: str
    capabilities: frozenset[str]
    model_profile: str
    max_context_items: int = 12


SPECIALISTS = {
    item.name: item for item in (
        SpecialistProfile("order", frozenset({"ORDER"}), "fast"),
        SpecialistProfile("logistics", frozenset({"SHIPPING"}), "fast"),
        SpecialistProfile("payment_refund", frozenset({"PAYMENT", "REFUND", "RETURN"}), "reasoning"),
        SpecialistProfile("policy", frozenset({"POLICY"}), "reasoning"),
        SpecialistProfile("product_checkout", frozenset({"PRODUCT", "CHECKOUT"}), "fast"),
        SpecialistProfile("safety_handoff", frozenset({"SAFETY"}), "reasoning"),
        SpecialistProfile("general", frozenset({"SOCIAL"}), "fast"),
    )
}


def validate_specialist_assignment(name: str, capability: str) -> None:
    profile = SPECIALISTS.get(name)
    if profile is None or capability not in profile.capabilities:
        raise ValueError("INVALID_SPECIALIST_ASSIGNMENT")
