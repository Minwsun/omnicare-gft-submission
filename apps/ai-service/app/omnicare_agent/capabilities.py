from __future__ import annotations

from dataclasses import dataclass

from .harness_contracts import AgentPlan, AgentTask, ExecutionBudget
from .registry import ToolRegistry
from .specialists import validate_specialist_assignment


@dataclass(frozen=True)
class Capability:
    name: str
    specialist: str
    evidence: tuple[str, ...] = ()
    preferred_tools: tuple[str, ...] = ()


CAPABILITIES = {
    "ORDER": Capability("ORDER", "order", ("ORDER", "CURRENT_STATUS"), ("get_order_details", "get_recent_orders", "get_order_summary", "find_eligible_orders")),
    "SHIPPING": Capability("SHIPPING", "logistics", ("SHIPMENT", "ETA"), ("get_order_details", "get_shipping_status")),
    "PAYMENT": Capability("PAYMENT", "payment_refund", ("PAYMENT",), ("get_order_details", "get_payment_status")),
    "REFUND": Capability("REFUND", "payment_refund", ("REFUND",), ("get_order_details", "get_refund_status")),
    "RETURN": Capability("RETURN", "payment_refund", ("ORDER_ITEMS", "RETURN_RULE"), ("get_order_details", "check_return_eligibility")),
    "POLICY": Capability("POLICY", "policy", ("ACTIVE_POLICY",), ("search_knowledge",)),
    "PRODUCT": Capability("PRODUCT", "product_checkout", ("PRODUCT", "AVAILABILITY"), ("search_products",)),
    "CHECKOUT": Capability("CHECKOUT", "product_checkout", ("PRODUCT", "ADDRESS", "QUOTE"), ("get_product_details", "get_customer_addresses", "quote_checkout")),
    "SAFETY": Capability("SAFETY", "safety_handoff", ("RISK",), ()),
    "SOCIAL": Capability("SOCIAL", "general", (), ()),
}


INTENT_CAPABILITIES = {
    "ORDER_TRACKING": ("ORDER", "SHIPPING"),
    "ORDER_CANCELLATION": ("ORDER",),
    "ACCOUNT_ORDERS": ("ORDER",),
    "PAYMENT_STATUS": ("ORDER", "PAYMENT"),
    "PAYMENT_POLICY": ("POLICY", "PAYMENT"),
    "REFUND_STATUS": ("ORDER", "REFUND"),
    "REFUND_POLICY": ("POLICY", "REFUND"),
    "RETURN_ELIGIBILITY": ("ORDER", "RETURN", "POLICY"),
    "RETURN_POLICY": ("POLICY", "RETURN"),
    "SHIPPING_POLICY": ("POLICY", "SHIPPING"),
    "PRODUCT_DISCOVERY": ("PRODUCT",),
    "ACCOUNT_SECURITY": ("SAFETY", "POLICY"),
    "FRAUD_WARNING": ("SAFETY",),
    "PRIVACY": ("POLICY", "SAFETY"),
    "PROMPT_INJECTION": ("SAFETY",),
    "HUMAN_REQUEST": ("SAFETY",),
    "SOCIAL": ("SOCIAL",),
    "OUT_OF_SCOPE": ("SAFETY",),
}


def capabilities_for_intents(intents: list[str]) -> list[str]:
    result: list[str] = []
    for intent in intents:
        inferred = INTENT_CAPABILITIES.get(intent)
        if inferred is None:
            inferred = ("POLICY",) if intent.endswith("POLICY") or intent in {"KNOWLEDGE", "VOUCHER", "TECHNICAL_SUPPORT"} else ("ORDER",)
        for capability in inferred:
            if capability not in result:
                result.append(capability)
    return result


def build_adaptive_plan(goal: str, intents: list[str], registry: ToolRegistry, customer_verified: bool, known_order: bool = False) -> AgentPlan:
    tasks: list[AgentTask] = []
    tool_count = 0
    transaction_without_order = not known_order and any(intent in {"ORDER_TRACKING", "ORDER_CANCELLATION", "PAYMENT_STATUS", "REFUND_STATUS", "RETURN_ELIGIBILITY"} for intent in intents)
    for index, name in enumerate(capabilities_for_intents(intents), 1):
        capability = CAPABILITIES[name]
        validate_specialist_assignment(capability.specialist, name)
        available = registry.tools_for_skills({name})
        preferred = [tool for tool in capability.preferred_tools if tool in available]
        if "ACCOUNT_ORDERS" in intents and name == "ORDER":
            preferred = [tool for tool in preferred if tool == "get_order_summary"]
        elif transaction_without_order:
            preferred = [tool for tool in preferred if tool == "find_eligible_orders"] if name == "ORDER" else []
        else:
            preferred = [tool for tool in preferred if tool not in {"get_order_summary", "find_eligible_orders"}]
        if known_order:
            preferred = [tool for tool in preferred if tool not in {"get_recent_orders", "find_eligible_orders"}]
        if not customer_verified:
            preferred = [tool for tool in preferred if tool in {"search_knowledge", "search_products", "get_product_details"}]
        remaining = max(0, 8 - tool_count)
        selected = preferred[:remaining]
        tool_count += len(selected)
        tasks.append(AgentTask(
            id=f"task-{index}", capability=name, objective=goal,
            specialist=capability.specialist, required_tools=selected,
            required_evidence=list(capability.evidence),
        ))
        if len({task.specialist for task in tasks}) >= 3:
            break
    return AgentPlan(
        goal=goal,
        tasks=tasks,
        budget=ExecutionBudget(),
        completion_criteria=["OWNERSHIP_VERIFIED", "CLAIMS_GROUNDED", "TOOL_POLICY_PASSED"],
    )
