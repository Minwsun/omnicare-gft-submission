from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool

from .tool_policy import ApprovalMode, ToolPolicyDecision, ToolRisk, evaluate_tool_policy

from ..tool_adapters import (
    cancel_order,
    check_return_eligibility,
    create_support_ticket,
    create_dispute,
    create_refund,
    create_return_request,
    create_shipping_investigation,
    get_active_incidents,
    get_customer_profile,
    get_order_details,
    get_order_summary,
    find_eligible_orders,
    get_payment_status,
    get_recent_orders,
    get_refund_status,
    get_shipping_status,
    search_knowledge,
    search_products,
    get_product_details,
    get_customer_addresses,
    quote_checkout,
    create_checkout_session,
    confirm_checkout,
)


@dataclass(frozen=True)
class ToolSpecification:
    tool: BaseTool
    operation: Literal["READ", "WRITE"]
    skills: frozenset[str]
    risk: ToolRisk = "LOW"
    allowed_roles: frozenset[str] = frozenset({"CUSTOMER", "ADMIN", "REVIEWER"})
    approval: ApprovalMode = "NONE"
    timeout_seconds: float = 8
    max_retries: int = 1
    idempotent: bool = True


class ToolRegistry:
    def __init__(self, specifications: list[ToolSpecification]) -> None:
        names = [specification.tool.name for specification in specifications]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate tool name")
        self._specifications = tuple(specifications)

    def all_tools(self) -> list[BaseTool]:
        return [specification.tool for specification in self._specifications]

    def read_tools(self) -> list[BaseTool]:
        return [specification.tool for specification in self._specifications if specification.operation == "READ"]

    def names(self) -> set[str]:
        return {specification.tool.name for specification in self._specifications}

    def tools_for_skills(self, skills: set[str]) -> set[str]:
        return {
            specification.tool.name
            for specification in self._specifications
            if specification.skills.intersection(skills)
        }

    def specification(self, name: str) -> ToolSpecification:
        for specification in self._specifications:
            if specification.tool.name == name:
                return specification
        raise KeyError(name)

    def authorize(self, name: str, actor_role: str, customer_verified: bool) -> ToolPolicyDecision:
        specification = self.specification(name)
        return evaluate_tool_policy(
            operation=specification.operation,
            risk=specification.risk,
            allowed_roles=specification.allowed_roles,
            actor_role=actor_role,
            customer_verified=customer_verified,
            approval=specification.approval,
        )


tool_registry = ToolRegistry([
    ToolSpecification(get_customer_profile, "READ", frozenset({"CUSTOMER", "TRANSACTION"})),
    ToolSpecification(get_recent_orders, "READ", frozenset({"ORDER", "TRANSACTION"})),
    ToolSpecification(get_order_summary, "READ", frozenset({"ORDER", "TRANSACTION"})),
    ToolSpecification(find_eligible_orders, "READ", frozenset({"ORDER", "TRANSACTION", "RETURN", "SHIPPING", "PAYMENT", "REFUND"})),
    ToolSpecification(get_order_details, "READ", frozenset({"ORDER", "TRANSACTION", "RETURN"})),
    ToolSpecification(get_shipping_status, "READ", frozenset({"SHIPPING", "ORDER"})),
    ToolSpecification(get_payment_status, "READ", frozenset({"PAYMENT", "ORDER"})),
    ToolSpecification(get_refund_status, "READ", frozenset({"REFUND", "ORDER"})),
    ToolSpecification(check_return_eligibility, "READ", frozenset({"RETURN", "ORDER"})),
    ToolSpecification(get_active_incidents, "READ", frozenset({"INCIDENT", "GENERAL"})),
    ToolSpecification(search_knowledge, "READ", frozenset({"KNOWLEDGE", "GENERAL", "POLICY"})),
    ToolSpecification(search_products, "READ", frozenset({"PRODUCT", "COMMERCE"})),
    ToolSpecification(get_product_details, "READ", frozenset({"PRODUCT", "COMMERCE"})),
    ToolSpecification(get_customer_addresses, "READ", frozenset({"CUSTOMER", "COMMERCE"})),
    ToolSpecification(quote_checkout, "READ", frozenset({"CHECKOUT", "COMMERCE"})),
    ToolSpecification(create_support_ticket, "WRITE", frozenset({"HANDOFF", "TICKET"}), risk="MEDIUM", approval="NONE"),
    ToolSpecification(cancel_order, "WRITE", frozenset({"ORDER", "CANCELLATION"}), risk="HIGH", approval="CUSTOMER_CONFIRMATION", idempotent=True),
    ToolSpecification(create_return_request, "WRITE", frozenset({"RETURN", "ORDER"}), risk="MEDIUM", approval="CUSTOMER_CONFIRMATION", idempotent=True),
    ToolSpecification(create_shipping_investigation, "WRITE", frozenset({"SHIPPING", "DISPUTE"}), risk="MEDIUM", approval="CUSTOMER_CONFIRMATION", idempotent=True),
    ToolSpecification(create_dispute, "WRITE", frozenset({"DISPUTE", "ORDER"}), risk="HIGH", approval="CUSTOMER_CONFIRMATION", idempotent=True),
    ToolSpecification(create_refund, "WRITE", frozenset({"REFUND", "ORDER"}), risk="CRITICAL", approval="HUMAN_APPROVAL", idempotent=True),
    ToolSpecification(create_checkout_session, "WRITE", frozenset({"CHECKOUT", "COMMERCE"}), risk="MEDIUM", approval="CUSTOMER_CONFIRMATION", idempotent=True),
    ToolSpecification(confirm_checkout, "WRITE", frozenset({"CHECKOUT", "ORDER", "COMMERCE"}), risk="HIGH", approval="CUSTOMER_CONFIRMATION", idempotent=True),
])
