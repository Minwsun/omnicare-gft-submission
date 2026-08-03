from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import re

from ..contracts import AdvisorEvidenceSummary, AdvisorRecommendation, GroundedAgentResponse, ResolutionOption, ResponseQualityReport, ToolStatus


Complexity = Literal["SIMPLE", "MODERATE", "COMPLEX", "HIGH_RISK"]


@dataclass(frozen=True)
class CasePlan:
    objective: str
    complexity: Complexity
    required_facts: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    retrieval_profiles: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    candidate_actions: tuple[str, ...] = ()
    mandatory_checks: tuple[str, ...] = field(default_factory=lambda: ("OWNERSHIP", "GROUNDING", "PERMISSION"))

    def as_event(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "complexity": self.complexity,
            "requiredFacts": list(self.required_facts),
            "requiredTools": list(self.required_tools),
        }


def build_case_plan(intent: str, content: str, order_id: str | None) -> CasePlan:
    text = content.casefold()
    high_risk = intent in {"ACCOUNT_SECURITY", "FRAUD_WARNING", "PRIVACY"} or any(term in text for term in ("otp", "xóa tài khoản", "người khác", "lừa đảo"))
    dispute = any(term in text for term in ("chưa nhận", "giao nhầm", "thiếu món", "sai hàng", "không giống mô tả", "tranh chấp"))
    ambiguous = order_id is None and intent in {"ORDER_TRACKING", "ORDER_CANCELLATION", "PAYMENT_STATUS", "REFUND_STATUS", "RETURN_ELIGIBILITY"}
    policy = intent.endswith("POLICY") or intent in {"VOUCHER", "PRIVACY", "ACCOUNT_SECURITY", "FRAUD_WARNING", "TECHNICAL_SUPPORT", "KNOWLEDGE"}
    if high_risk:
        complexity: Complexity = "HIGH_RISK"
    elif dispute or ambiguous:
        complexity = "COMPLEX"
    elif policy:
        complexity = "MODERATE"
    else:
        complexity = "SIMPLE"
    tools = {
        "ORDER_TRACKING": ("get_order_details", "get_shipping_status") if order_id else ("find_eligible_orders",),
        "ORDER_CANCELLATION": ("get_order_details",) if order_id else ("get_recent_orders",),
        "PAYMENT_STATUS": ("get_order_details", "get_payment_status") if order_id else ("find_eligible_orders",),
        "REFUND_STATUS": ("get_order_details", "get_refund_status") if order_id else ("find_eligible_orders",),
        "RETURN_ELIGIBILITY": ("get_order_details", "check_return_eligibility") if order_id else ("find_eligible_orders",),
        "ACCOUNT_ORDERS": ("get_order_summary",),
    }.get(intent, ("search_knowledge",) if policy else ())
    facts = ("ORDER", "CURRENT_STATUS") if order_id else ()
    if intent == "ORDER_TRACKING":
        facts += ("SHIPMENT", "ETA")
    elif intent == "PAYMENT_STATUS":
        facts += ("PAYMENT",)
    elif intent == "REFUND_STATUS":
        facts += ("REFUND",)
    elif intent == "RETURN_ELIGIBILITY":
        facts += ("ORDER_ITEMS", "RETURN_RULE")
    return CasePlan(
        objective=intent,
        complexity=complexity,
        required_facts=facts,
        required_tools=tools,
        retrieval_profiles=(intent,),
        unresolved_questions=("ORDER_ID",) if ambiguous else (),
        candidate_actions=("HANDOFF",) if high_risk else ("CLARIFY", "RECOMMEND", "HANDOFF"),
    )


def enrich_advisor_response(response: GroundedAgentResponse, plan: CasePlan) -> GroundedAgentResponse:
    response.complexity = plan.complexity
    response.case_state = "HANDOFF" if response.requires_human else "AWAITING_CONFIRMATION" if response.pending_action else "AWAITING_INPUT" if response.ui else "RESOLVED"
    successful_tools = [item.name for item in response.tool_calls if item.status == ToolStatus.SUCCESS]
    transaction_facts = [f"{name}: verified" for name in successful_tools if name != "search_knowledge"]
    policy_claims = [f"{item.title} · {item.version}" for item in response.citations]
    response.evidence_summary = AdvisorEvidenceSummary(transaction_facts=transaction_facts, policy_claims=policy_claims)
    if response.requires_human:
        response.diagnosis = "Tình huống cần nhân viên kiểm tra thêm trước khi kết luận hoặc thực hiện hành động."
        response.recommendation = AdvisorRecommendation(option_id="human-review", summary="Chuyển nhân viên hỗ trợ", reason=response.escalation_reason or "Thiếu dữ liệu hoặc quyền xử lý tự động.")
        response.alternatives = [ResolutionOption(id="human-review", title="Nhân viên kiểm tra", outcome="Case được tiếp nhận cùng toàn bộ lịch sử và evidence.", eligibility="ELIGIBLE")]
    elif response.pending_action:
        response.diagnosis = "Dữ liệu hiện tại cho phép gửi yêu cầu, nhưng cần bạn xác nhận trước."
        response.recommendation = AdvisorRecommendation(option_id=response.pending_action.action.lower(), summary=response.answer, reason="Trạng thái và quyền hành động đã được xác minh.")
    elif plan.complexity in {"COMPLEX", "HIGH_RISK"} and successful_tools:
        response.diagnosis = "Đã đối chiếu dữ liệu giao dịch hiện tại và chọn bước xử lý ít rủi ro nhất."
        response.recommendation = AdvisorRecommendation(option_id="recommended-next-step", summary=response.answer, reason="Khuyến nghị dựa trên dữ liệu vừa tra cứu và giới hạn quyền tự động.")
    response.missing_facts = list(plan.unresolved_questions)
    return response


def validate_advisor_response(response: GroundedAgentResponse, plan: CasePlan) -> list[str]:
    errors: list[str] = []
    successful = {item.name for item in response.tool_calls if item.status == ToolStatus.SUCCESS}
    if plan.required_tools and not successful.intersection(plan.required_tools):
        errors.append("REQUIRED_EVIDENCE_MISSING")
    if response.recommendation and not response.answer.strip():
        errors.append("EMPTY_RECOMMENDATION_ANSWER")
    if response.pending_action and response.case_state != "AWAITING_CONFIRMATION":
        errors.append("INVALID_PENDING_ACTION_STATE")
    if response.requires_human and response.case_state != "HANDOFF":
        errors.append("INVALID_HANDOFF_STATE")
    return errors


def review_response(content: str, response: GroundedAgentResponse) -> GroundedAgentResponse:
    propositions = [part.strip(" .?!") for part in re.split(r"\b(?:và|rồi|đồng thời)\b|[?;]", content, flags=re.IGNORECASE) if len(part.strip(" .?!")) > 2]
    answer = response.answer.casefold()
    answered = [item for item in propositions if any(term in answer for term in re.findall(r"[\wÀ-ỹ]{4,}", item.casefold()))]
    unanswered = [item for item in propositions if item not in answered]
    technical_terms = [term for term in ("evidence", "retrieval", "graph", "toolresult", "json") if term in answer]
    next_step_terms = ("bạn có thể", "bạn chọn", "bạn kiểm tra", "gửi", "xác nhận", "liên hệ", "mình sẽ", "mình có thể", "thử")
    missing_next_step = response.requires_human is False and response.pending_action is None and not any(term in answer for term in next_step_terms)
    score = 1 if not propositions else len(answered) / len(propositions)
    response.quality = ResponseQualityReport(
        coverage_score=score,
        propositions=propositions,
        answered_propositions=answered,
        unanswered_propositions=unanswered,
        unsupported_claims=technical_terms,
        missing_next_step=missing_next_step,
    )
    if technical_terms:
        response.answer = re.sub(r"\b(?:evidence|retrieval|graph|ToolResult|JSON)\b", "thông tin", response.answer, flags=re.IGNORECASE)
    return response
