from __future__ import annotations

import re
import unicodedata

from ..contracts import GroundedAgentResponse, ToolStatus
from .harness_contracts import ReviewVerdict


ORDER_PATTERN = re.compile(r"\bORD-[A-Z0-9]{4,}\b", re.IGNORECASE)

POSITIVE_CLAIMS_BY_TOOL = {
    "get_shipping_status": ("dang giao", "dang duoc giao", "dang van chuyen", "du kien giao", "don vi van chuyen"),
    "get_payment_status": ("da thanh toan", "thanh toan thanh cong"),
    "get_refund_status": ("dang hoan tien", "hoan tien thanh cong", "da hoan tien"),
}


def _plain_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn").replace("đ", "d")


def _asserts_positive_claim(answer: str, phrases: tuple[str, ...]) -> bool:
    text = _plain_text(answer)
    for phrase in phrases:
        start = text.find(phrase)
        if start < 0:
            continue
        prefix = text[max(0, start - 64):start]
        if not any(negation in prefix for negation in ("khong", "chua", "khong tim thay", "khong con")):
            return True
    return False


def review_grounded_response(response: GroundedAgentResponse, required_tools: tuple[str, ...] = ()) -> ReviewVerdict:
    errors: list[str] = []
    conclusive = {item.name for item in response.tool_calls if item.status in {ToolStatus.SUCCESS, ToolStatus.NOT_FOUND}}
    missing_required = set(required_tools).difference(conclusive)
    if missing_required and response.confidence > 0.7:
        errors.append("REQUIRED_TOOL_EVIDENCE_MISSING")
    for item in response.tool_calls:
        phrases = POSITIVE_CLAIMS_BY_TOOL.get(item.name, ())
        if item.status == ToolStatus.NOT_FOUND and phrases and _asserts_positive_claim(response.answer, phrases):
            errors.append("POSITIVE_CLAIM_WITHOUT_TOOL_EVIDENCE")
    expected_order = str(response.resolved_context.get("orderId") or "").upper()
    mentioned_orders = {item.upper() for item in ORDER_PATTERN.findall(response.answer)}
    if expected_order and any(item != expected_order for item in mentioned_orders):
        errors.append("ORDER_ID_MISMATCH")
    if response.actions and any(action.status == "COMPLETED" for action in response.actions) and not any(item.status == ToolStatus.SUCCESS for item in response.tool_calls):
        errors.append("COMPLETED_ACTION_WITHOUT_SUCCESSFUL_TOOL")
    if response.citations and any(not citation.document_id or not citation.version for citation in response.citations):
        errors.append("INVALID_CITATION_BINDING")
    if response.requires_human and not response.escalation_reason:
        errors.append("HANDOFF_REASON_REQUIRED")
    if response.quality.missing_next_step and response.confidence > 0.7 and not response.pending_action:
        errors.append("MISSING_NEXT_STEP")
    return ReviewVerdict(status="FALLBACK" if errors else "PASSED", errors=errors, coverage=response.quality.coverage_score)
