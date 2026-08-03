from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, AsyncIterator
from uuid import uuid4
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from ..contracts import AgentChoice, AgentUiComponent, Citation, CustomerContextUsed, GroundedAgentResponse, IncomingMessage, PendingAgentAction, ToolExecutionSummary, ToolStatus, VerifiedDataBinding, VerifiedFact
from ..config import settings
from ..models import configured_model, load_system_prompt
from ..repositories import repository
from ..retrieval import retrieve
from ..contracts import RetrievalRequest
from ..tools import check_return_eligibility, create_checkout_session, find_eligible_orders, get_order_details, get_order_summary, get_payment_status, get_recent_orders, get_refund_status, get_shipping_status, search_products
from .confirmation import create_confirmation_token
from .context import TrustedContext
from .registry import ToolRegistry, tool_registry
from .advisor import CasePlan, enrich_advisor_response, review_response, validate_advisor_response
from .supervisor import SupervisorHarness
from .executor import tool_executor
from .reviewer import review_grounded_response
from .model_router import select_model_profile


ORDER_PATTERN = re.compile(r"\bord\s*[-_ ]?\s*([a-z0-9]{4,})\b", re.IGNORECASE)
VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

STATUS_LABELS = {
    "PENDING": "đang chờ xác nhận",
    "CONFIRMED": "shop đã xác nhận",
    "PROCESSING": "shop đang chuẩn bị hàng",
    "SHIPPED": "đã bàn giao cho đơn vị vận chuyển",
    "OUT_FOR_DELIVERY": "đang được giao tới bạn",
    "DELIVERED": "đã giao thành công",
    "CANCELLED": "đã hủy",
}

PAYMENT_LABELS = {
    "PENDING": "đang chờ thanh toán",
    "AUTHORIZED": "đã được ngân hàng xác nhận",
    "CAPTURED": "đã thanh toán thành công",
    "FAILED": "thanh toán chưa thành công",
    "REFUNDED": "đã hoàn tiền",
}

REFUND_LABELS = {
    "REQUESTED": "đã tiếp nhận yêu cầu hoàn tiền",
    "PENDING": "đang xử lý hoàn tiền",
    "APPROVED": "đã duyệt hoàn tiền",
    "COMPLETED": "đã hoàn tiền thành công",
    "REJECTED": "yêu cầu hoàn tiền không được chấp nhận",
}


def normalize_support_text(content: str) -> str:
    text = content.casefold()
    replacements = {
        r"\bko\b": "không",
        r"\bk\b": "không",
        r"\bdc\b": "được",
        r"\bđc\b": "được",
        r"\bhuỷ\b": "hủy",
        r"\btar\b": "trả",
        r"\btra hang\b": "trả hàng",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text


def fuzzy_phrase(text: str, phrases: tuple[str, ...], threshold: float = 0.82) -> bool:
    ascii_text = "".join(character for character in unicodedata.normalize("NFKD", text) if not unicodedata.combining(character)).replace("đ", "d")
    words = re.findall(r"[a-z0-9]+", ascii_text)
    for phrase in phrases:
        ascii_phrase = "".join(character for character in unicodedata.normalize("NFKD", phrase) if not unicodedata.combining(character)).replace("đ", "d")
        phrase_words = ascii_phrase.split()
        for size in range(max(1, len(phrase_words) - 1), len(phrase_words) + 2):
            for index in range(max(0, len(words) - size + 1)):
                if SequenceMatcher(None, " ".join(words[index:index + size]), ascii_phrase).ratio() >= threshold:
                    return True
    return False


def human_handoff_signal(content: str) -> tuple[bool, float]:
    text = normalize_support_text(content)
    ascii_text = "".join(character for character in unicodedata.normalize("NFKD", text) if not unicodedata.combining(character)).replace("đ", "d")
    words = re.findall(r"[a-z0-9]+", ascii_text)
    if any(phrase in ascii_text for phrase in ("khong can gap", "khong muon gap", "dung chuyen", "khong can nhan vien", "khong can tu van vien")):
        return False, 1.0
    if any(phrase in ascii_text for phrase in ("lam viec luc", "gio nao", "may gio", "thoi gian lam viec")):
        return False, 1.0

    role_phrases = ("nhan vien", "tu van vien", "cham soc khach hang", "nguoi ho tro", "nguoi that", "quan ly", "support agent", "cskh")
    role_span: tuple[int, int] | None = None
    role_score = 0.0
    for phrase in role_phrases:
        phrase_words = phrase.split()
        for size in range(max(1, len(phrase_words) - 1), len(phrase_words) + 2):
            for index in range(len(words) - size + 1):
                candidate = " ".join(words[index:index + size])
                score = 1.0 if candidate == phrase else SequenceMatcher(None, candidate, phrase).ratio()
                if score > role_score:
                    role_score = score
                    role_span = (index, index + size)
    if role_span is None or role_score < 0.82:
        return False, 0.0

    start, end = role_span
    nearby = words[max(0, start - 5):min(len(words), end + 5)]
    nearby_text = " ".join(nearby)
    exact_actions = ("gap", "cho gap", "can gap", "muon gap", "noi chuyen voi", "ket noi", "lien he", "chuyen den", "chuyen cho", "goi")
    action_score = 1.0 if any(action in nearby_text for action in exact_actions) else 0.0
    for word in nearby:
        action_score = max(action_score, SequenceMatcher(None, word, "gap").ratio())
    requested_role = any(word in nearby for word in ("can", "muon", "cho"))
    requested = action_score >= 0.72 or (requested_role and role_score >= 0.9)
    confidence = min(0.99, (role_score + max(action_score, 0.8 if requested_role else 0.0)) / 2)
    return requested, confidence if requested else 0.0


def normalize_order_id(content: str, page_context: dict[str, Any] | None = None) -> str | None:
    match = ORDER_PATTERN.search(content)
    if match:
        return f"ORD-{match.group(1).upper()}"
    bare = re.fullmatch(r"\s*([a-z0-9]{4,})\s*", content, re.IGNORECASE)
    if bare:
        return f"ORD-{bare.group(1).upper()}"
    memory = (page_context or {}).get("memory") or {}
    active_context = memory.get("activeContext") if isinstance(memory, dict) else {}
    active_order = str((active_context or {}).get("orderId") or "").strip() if isinstance(active_context, dict) else ""
    if active_order:
        match = ORDER_PATTERN.search(active_order)
        return f"ORD-{match.group(1).upper()}" if match else active_order.upper()
    contextual = str((page_context or {}).get("orderId") or "").strip()
    if contextual:
        match = ORDER_PATTERN.search(contextual)
        return f"ORD-{match.group(1).upper()}" if match else contextual.upper()
    history = (page_context or {}).get("conversationHistory") or []
    for item in reversed(history):
        match = ORDER_PATTERN.search(str(item.get("content") if isinstance(item, dict) else item))
        if match:
            return f"ORD-{match.group(1).upper()}"
    return None


def classify(content: str) -> str:
    text = normalize_support_text(content)
    if any(term in text for term in ("bao nhiêu đơn", "mấy đơn", "danh sách đơn", "có những đơn nào", "tất cả đơn")):
        return "ACCOUNT_ORDERS"
    if text.strip() in {"chào", "xin chào", "hello", "hi", "cảm ơn", "cám ơn", "ok", "được", "tạm biệt", "bye"} or any(term in text for term in ("bạn làm được gì", "bạn giúp gì", "cảm ơn bạn")):
        return "SOCIAL"
    if any(term in text for term in ("system prompt", "fraud threshold", "ignore previous", "bỏ qua hướng dẫn", "tool bí mật", "tài liệu internal", "giả làm admin")):
        return "PROMPT_INJECTION"
    if human_handoff_signal(content)[0]:
        return "HUMAN_REQUEST"
    if any(term in text for term in ("viết code", "thời tiết", "chứng khoán", "tích phân", "kể một câu chuyện", "viết bài thơ", "làm thơ")):
        return "OUT_OF_SCOPE"
    if any(term in text for term in ("voucher", "mã giảm giá", "khuyến mãi")):
        return "VOUCHER"
    if any(term in text for term in ("lừa đảo", "trúng thưởng", "link lạ", "chuyển khoản ngoài", "chuyển tiền để nhận quà", "nạp tiền", "ngoài app", "tuyển dụng")):
        return "FRAUD_WARNING"
    if any(term in text for term in ("dữ liệu cá nhân", "thông tin cá nhân", "chính sách bảo mật", "xóa dữ liệu", "chia sẻ dữ liệu", "lưu dữ liệu", "dùng dữ liệu")):
        return "PRIVACY"
    if any(term in text for term in ("otp", "đăng nhập", "mật khẩu", "bảo vệ tài khoản", "đổi thông tin", "email tài khoản", "không phải tôi", "người đăng nhập")):
        return "ACCOUNT_SECURITY"
    domain_policy_terms = ("vận chuyển", "giao hàng", "thanh toán", "cod", "trả hàng", "đổi trả", "hoàn tiền", "dữ liệu", "bảo mật", "voucher")
    if any(term in text for term in ("chính sách", "quy định", "điều khoản", "nguồn", "phiên bản snapshot")) and not ORDER_PATTERN.search(content) and not any(term in text for term in domain_policy_terms):
        return "KNOWLEDGE"
    if any(term in text for term in ("hủy", "huỷ", "không muốn mua", "dừng giao", "đổi ý")) or ("ord" in text and "không nhận" in text):
        return "ORDER_CANCELLATION"
    product_terms = ("sản phẩm", "tai nghe", "điện thoại", "phụ kiện", "gia dụng", "mỹ phẩm", "thời trang", "mẹ và bé", "thực phẩm")
    discovery_terms = ("gợi ý", "tư vấn", "muốn mua", "tìm", "mua", "đặt")
    if any(product in text for product in product_terms) and any(term in text for term in discovery_terms):
        return "PRODUCT_DISCOVERY"
    return_issue = any(term in text for term in ("trả hàng", "trả đơn", "đổi trả", "sai hàng", "sai sản phẩm", "nhận sai", "thiếu hàng", "thiếu sản phẩm", "thiếu món", "không giống mô tả", "bị hỏng", "hàng lỗi"))
    product_failure = any(term in text for term in ("bị lỗi", "lỗi rồi")) and any(term in text for term in ("sản phẩm", "hàng", "ord"))
    if return_issue or product_failure:
        return "RETURN_ELIGIBILITY" if "ord" in text else "RETURN_POLICY"
    if any(term in text for term in ("hoàn tiền", "refund", "tiền hoàn", "tiền về chưa", "yêu cầu hoàn")):
        return "REFUND_STATUS" if "ord" in text else "REFUND_POLICY"
    if any(term in text for term in ("thanh toán", "trừ tiền", "trả tiền", "tiền đơn", "cod", "thẻ")):
        return "PAYMENT_STATUS" if "ord" in text else "PAYMENT_POLICY"
    if "ord" in text and any(term in text for term in ("chưa nhận", "không thấy hàng", "đã giao", "giao cho ai", "giao nhầm", "đang ở đâu", "tới đâu", "khi nào", "lâu vậy")):
        return "ORDER_TRACKING"
    if any(term in text for term in ("app", "ứng dụng", "thông báo", "bộ nhớ", "cập nhật")):
        return "TECHNICAL_SUPPORT"
    if any(term in text for term in ("địa chỉ sau khi đặt", "đổi địa chỉ", "chính sách vận chuyển", "hỏi giao", "liên hệ đơn vị vận chuyển")):
        return "SHIPPING_POLICY"
    commerce_actions = ("đặt đơn", "tạo đơn", "mua hàng", "mua ngay", "chốt mua", "đặt hàng", "đặt sản phẩm")
    if any(term in text for term in commerce_actions) or fuzzy_phrase(text, commerce_actions):
        return "PRODUCT_DISCOVERY"
    if any(term in text for term in ("đang ở đâu", "tới đâu", "giao chưa", "shipper", "hành trình", "khi nào tới", "khi nào được giao", "bao giờ giao", "eta", "chưa nhận", "không thấy hàng", "giao cho ai", "giao nhầm", "đơn đã giao", "lâu vậy")):
        return "ORDER_TRACKING" if "ord" in text else "SHIPPING_POLICY"
    if any(term in text for term in ("đơn quốc tế", "theo dõi quốc tế", "địa chỉ sau khi đặt", "chính sách vận chuyển", "hối giao", "liên hệ đơn vị vận chuyển")):
        return "SHIPPING_POLICY"
    if "ord" in text and any(term in text for term in ("xem đơn", "kiểm tra đơn", "đơn ord", "giao không", "tình trạng đơn", "khi nào", "người nhận")):
        return "ORDER_TRACKING"
    return "KNOWLEDGE"


def requests_policy_conflict_resolution(content: str) -> bool:
    text = content.casefold()
    has_conflict = any(term in text for term in ("mâu thuẫn", "xung đột", "trái nhau"))
    compares_policies = any(term in text for term in (
        "hai policy", "2 policy", "policy với policy",
        "hai chính sách", "2 chính sách", "chính sách với chính sách",
        "hai quy định", "2 quy định", "hai điều khoản", "2 điều khoản",
    ))
    return has_conflict and compares_policies


def format_money(value: Any, currency: str = "VND") -> str:
    try:
        amount = f"{float(value):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return ""
    return f"{amount}₫" if currency == "VND" else f"{amount} {currency}"


def format_datetime(value: Any) -> str:
    if not value:
        return ""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(VIETNAM_TZ)
    return parsed.strftime("%H:%M ngày %d/%m/%Y")


def tool_summary(name: str, result: Any) -> ToolExecutionSummary:
    return ToolExecutionSummary(name=name, status=result.status, reference_id=result.reference_id)


def verified_facts(source: str, result: Any, keys: tuple[str, ...]) -> list[VerifiedFact]:
    data = result.data or {}
    return [VerifiedFact(key=key, value=data[key], source=source, reference_id=result.reference_id, observed_at=result.observed_at) for key in keys if data.get(key) is not None]


class OmniCareAgentRuntime:
    def __init__(self, registry: ToolRegistry, checkpointer=None) -> None:
        self.registry = registry
        self.executor = tool_executor
        self.supervisor = SupervisorHarness(classify, normalize_support_text, normalize_order_id, checkpointer)

    @classmethod
    def create(cls, checkpointer=None, registry: ToolRegistry = tool_registry) -> "OmniCareAgentRuntime":
        return cls(registry, checkpointer)

    @staticmethod
    async def _record_gap(query: str, reason: str) -> str | None:
        try:
            return await repository.record_knowledge_gap(query, reason)
        except Exception:
            return None

    async def run(self, message: IncomingMessage) -> GroundedAgentResponse:
        final: GroundedAgentResponse | None = None
        async for event, payload in self.stream(message):
            if event == "done":
                final = payload
        if final is None:
            raise RuntimeError("Agent did not return a final response")
        return final

    async def stream(self, message: IncomingMessage) -> AsyncIterator[tuple[str, Any]]:
        context = TrustedContext.from_message(message)
        prepared = await self.supervisor.prepare(message)
        route = prepared["route"]
        intent = route.primary_intent
        order_id = prepared.get("order_id")
        plan = prepared["plan"]
        tool_policy = prepared.get("tool_policy", {})
        model_decision = select_model_profile(
            intent,
            plan,
            route.secondary_intents,
            prepared.get("risk_flags", []),
            route_confidence=route.confidence,
        )
        yield "planning", {**plan.as_event(), "routeConfidence": route.confidence, "secondaryIntents": route.secondary_intents, "proposition": route.proposition, "riskFlags": prepared.get("risk_flags", []), "agentPlan": prepared.get("adaptive_plan", {}), "skills": prepared.get("selected_skills", [])}
        yield "understanding", {"canonicalQuery": prepared.get("canonical_query", message.content), "confidence": prepared.get("semantic_confidence", route.confidence), "fallback": prepared.get("understanding_fallback", False)}
        yield "model_selected", model_decision.model_dump(mode="json")
        adaptive_plan = prepared.get("adaptive_plan", {})
        for task in adaptive_plan.get("tasks", []):
            yield "specialist_selected", {
                "taskId": task.get("id"),
                "specialist": task.get("specialist"),
                "capability": task.get("capability"),
                "requiredTools": task.get("required_tools", []),
                "requiredEvidence": task.get("required_evidence", []),
            }
        yield "tool_policy", tool_policy
        denied_tools = [name for name, decision in tool_policy.items() if not decision.get("allowed")]
        if denied_tools:
            response = GroundedAgentResponse(
                answer="Mình chưa thể thực hiện bước tra cứu hoặc hành động này với quyền hiện tại. Mình sẽ chuyển nhân viên hỗ trợ kiểm tra an toàn cho bạn.",
                confidence=1,
                intent=intent,
                requires_human=True,
                escalation_reason=f"TOOL_POLICY_DENIED:{','.join(denied_tools)}",
            )
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return

        if intent == "SOCIAL":
            response = GroundedAgentResponse(answer=self._social_answer(message.content), confidence=1, intent=intent, conversation_mode="SOCIAL", resolved_context={"orderId": order_id} if order_id else {})
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return

        if intent == "PROMPT_INJECTION":
            response = GroundedAgentResponse(answer="Mình không thể cung cấp hướng dẫn nội bộ, quyền truy cập hoặc dữ liệu bảo mật. Mình vẫn có thể hỗ trợ đơn hàng, thanh toán, trả hàng và các vấn đề mua sắm của bạn.", confidence=1, intent=intent, conversation_mode="DOMAIN")
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        if intent == "OUT_OF_SCOPE":
            response = GroundedAgentResponse(answer=self._out_of_scope_answer(message.content), confidence=1, intent=intent, conversation_mode="OUT_OF_SCOPE")
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        if intent == "HUMAN_REQUEST":
            response = GroundedAgentResponse(answer="Được, mình sẽ chuyển toàn bộ nội dung cuộc trò chuyện này cho nhân viên hỗ trợ. Bạn không cần kể lại từ đầu nhé.", confidence=1, intent=intent, requires_human=True, escalation_reason="CUSTOMER_REQUEST")
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        if intent == "ACCOUNT_ORDERS":
            yield "tool_started", {"tools": ["get_order_summary"]}
            summary = await get_order_summary(context.tool_context())
            response = self._order_summary(summary)
            yield "tool_completed", {"tools": [item.model_dump(mode="json") for item in response.tool_calls]}
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        if requests_policy_conflict_resolution(message.content):
            response = GroundedAgentResponse(
                answer="Hai chính sách đang mâu thuẫn nên mình không thể tự chọn một bản để áp dụng. Mình sẽ chuyển trường hợp này cho nhân viên xác minh chính sách đang có hiệu lực.",
                confidence=1,
                intent="KNOWLEDGE",
                requires_human=True,
                escalation_reason="POLICY_CONFLICT",
                conversation_mode="DOMAIN",
            )
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        transaction_intents = list(dict.fromkeys([intent, *route.secondary_intents]))
        supported_multi = {"ORDER_CANCELLATION", "ORDER_TRACKING", "PAYMENT_STATUS", "REFUND_STATUS", "RETURN_ELIGIBILITY"}
        transaction_intents = [item for item in transaction_intents if item in supported_multi]
        if settings.harness_v3_enabled and len(transaction_intents) > 1:
            combined_plans = [build_case_plan(item, message.content, order_id) for item in transaction_intents]
            combined_plan = CasePlan(
                objective="MULTI_INTENT",
                complexity="COMPLEX",
                required_facts=tuple(dict.fromkeys(fact for item in combined_plans for fact in item.required_facts)),
                required_tools=tuple(dict.fromkeys(tool for item in combined_plans for tool in item.required_tools)),
                retrieval_profiles=tuple(transaction_intents),
                candidate_actions=("CLARIFY", "RECOMMEND", "HANDOFF"),
            )
            yield "tool_started", {"tools": list(combined_plan.required_tools), "parallel": True}
            response = await self._multi_transaction(transaction_intents, message, context, order_id)
            yield "tool_completed", {"tools": [item.model_dump(mode="json") for item in response.tool_calls]}
            self._attach_context(response, "MULTI_INTENT", order_id, message)
            yield "reviewing", {"checks": list(combined_plan.mandatory_checks)}
            response = self._finalize(response, combined_plan, message.content)
            yield "validation", {"status": response.review_status}
            async for item in self._emit(response):
                yield item
            return
        if intent == "PRODUCT_DISCOVERY":
            yield "tool_started", {"tools": ["search_products"]}
            response = await self._product_discovery(message, context)
            yield "tool_completed", {"tools": [item.model_dump(mode="json") for item in response.tool_calls]}
            yield "reviewing", {"checks": list(plan.mandatory_checks)}
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        if intent == "ORDER_CANCELLATION":
            yield "tool_started", {"tools": list(plan.required_tools)}
            response = await self._cancellation(message, context, order_id)
            yield "tool_completed", {"tools": [item.model_dump(mode="json") for item in response.tool_calls]}
            self._attach_context(response, intent, order_id, message)
            yield "reviewing", {"checks": list(plan.mandatory_checks)}
            response = self._finalize(response, plan, message.content)
            yield "validation", {"status": "PASSED"}
            async for item in self._emit(response):
                yield item
            return
        if intent in {"ORDER_TRACKING", "PAYMENT_STATUS", "REFUND_STATUS", "RETURN_ELIGIBILITY"}:
            yield "tool_started", {"tools": list(plan.required_tools)}
            response = await self._transaction(intent, context, order_id, message.content, message)
            yield "tool_completed", {"tools": [item.model_dump(mode="json") for item in response.tool_calls]}
            self._attach_context(response, intent, order_id, message)
            yield "reviewing", {"checks": list(plan.mandatory_checks)}
            response = self._finalize(response, plan, message.content)
            yield "validation", {"status": "PASSED"}
            async for item in self._emit(response):
                yield item
            return

        async for item in self._knowledge_stream(message, intent, order_id, plan, route.proposition):
            yield item

    async def _multi_transaction(self, intents: list[str], message: IncomingMessage, context: TrustedContext, order_id: str | None) -> GroundedAgentResponse:
        async def run_intent(item: str) -> GroundedAgentResponse:
            if item == "ORDER_CANCELLATION":
                return await self._cancellation(message, context, order_id)
            return await self._transaction(item, context, order_id, message.content, message)

        responses = await asyncio.gather(*(run_intent(item) for item in intents))
        return GroundedAgentResponse(
            answer="\n\n".join(response.answer for response in responses if response.answer),
            confidence=min(response.confidence for response in responses),
            intent="MULTI_INTENT",
            citations=list({(citation.document_id, citation.version): citation for response in responses for citation in response.citations}.values()),
            customer_context_used=[item for response in responses for item in response.customer_context_used],
            verified_facts=[item for response in responses for item in response.verified_facts],
            actions=[item for response in responses for item in response.actions],
            tool_calls=[item for response in responses for item in response.tool_calls],
            ui=[item for response in responses for item in response.ui],
            pending_action=next((response.pending_action for response in responses if response.pending_action), None),
            conversation_state="AWAITING_CONFIRMATION" if any(response.pending_action for response in responses) else "ANSWERED",
            requires_human=any(response.requires_human for response in responses),
            escalation_reason=next((response.escalation_reason for response in responses if response.escalation_reason), None),
        )

    async def _transaction(self, intent: str, context: TrustedContext, order_id: str | None, content: str, message: IncomingMessage | None = None) -> GroundedAgentResponse:
        if not order_id:
            goal = {
                "ORDER_TRACKING": "IN_TRANSIT",
                "PAYMENT_STATUS": "PAYMENT_RELEVANT",
                "REFUND_STATUS": "REFUND_RELEVANT",
                "RETURN_ELIGIBILITY": "RETURNABLE",
            }[intent]
            eligible = await find_eligible_orders(context.tool_context(), goal)
            return self._order_selector(eligible, "Mình đã xem các đơn phù hợp trong tài khoản. Bạn chọn đơn cần kiểm tra nhé.", message=message, resume_intent=intent, tool_name="find_eligible_orders")

        specialized = {
            "ORDER_TRACKING": get_shipping_status,
            "PAYMENT_STATUS": get_payment_status,
            "REFUND_STATUS": get_refund_status,
        }.get(intent)
        if intent == "RETURN_ELIGIBILITY":
            reason = self._return_reason(content)
            if settings.harness_v3_enabled:
                records = await self.executor.execute_parallel([
                    ("get_order_details", context.actor_role, bool(context.customer_id), lambda: get_order_details(context.tool_context(), order_id)),
                    ("check_return_eligibility", context.actor_role, bool(context.customer_id), lambda: check_return_eligibility(context.tool_context(), order_id, reason)),
                ])
                details, result = records[0].result, records[1].result
            else:
                details, result = await asyncio.gather(get_order_details(context.tool_context(), order_id), check_return_eligibility(context.tool_context(), order_id, reason))
            calls = [tool_summary("get_order_details", details), tool_summary("check_return_eligibility", result)]
        else:
            if settings.harness_v3_enabled:
                records = await self.executor.execute_parallel([
                    ("get_order_details", context.actor_role, bool(context.customer_id), lambda: get_order_details(context.tool_context(), order_id)),
                    (specialized.__name__, context.actor_role, bool(context.customer_id), lambda: specialized(context.tool_context(), order_id)),
                ])
                details, result = records[0].result, records[1].result
            else:
                details, result = await asyncio.gather(get_order_details(context.tool_context(), order_id), specialized(context.tool_context(), order_id))
            calls = [tool_summary("get_order_details", details), tool_summary(specialized.__name__, result)]

        if details.status != ToolStatus.SUCCESS:
            return GroundedAgentResponse(answer=f"Mình không xem được đơn {order_id} bằng tài khoản này. Bạn thử đăng nhập đúng tài khoản đã đặt đơn; nếu vẫn không thấy, mình sẽ chuyển nhân viên kiểm tra giúp.", confidence=0.2, tool_calls=calls, requires_human=details.status == ToolStatus.FORBIDDEN, escalation_reason=details.error_code)
        if result.status not in {ToolStatus.SUCCESS, ToolStatus.NOT_FOUND}:
            return GroundedAgentResponse(answer=result.safe_message or "Mình chưa thể tra cứu dữ liệu mới nhất cho đơn này.", confidence=0.3, tool_calls=calls, requires_human=True, escalation_reason=result.error_code)

        data = result.data or {}
        if intent == "ORDER_TRACKING":
            order_data = details.data or {}
            order_status = str(order_data.get("status") or "")
            normalized_content = normalize_support_text(content)
            challenge = any(term in normalized_content for term in ("tại sao", "sao bạn", "vì sao", "bạn lại báo", "bạn nói"))
            if order_status == "CANCELLED":
                prefix = "Mình xin lỗi, câu trả lời trước chưa chính xác. " if challenge else ""
                answer = f"{prefix}Đơn {order_id} hiện đã hủy, nên không còn ở trạng thái giao hàng."
                if result.status == ToolStatus.NOT_FOUND:
                    answer += " Hệ thống cũng không tìm thấy hành trình vận chuyển đang hoạt động cho đơn này."
                answer += " Nếu bạn đã thanh toán, mình có thể kiểm tra tiếp trạng thái hoàn tiền."
                return GroundedAgentResponse(
                    answer=answer,
                    confidence=1 if result.status == ToolStatus.NOT_FOUND else 0.9,
                    tool_calls=calls,
                    verified_facts=verified_facts("get_order_details", details, ("status", "updatedAt")),
                    customer_context_used=[CustomerContextUsed(type="ORDER", reference_id=order_id, observed_at=details.observed_at)],
                )
            if result.status == ToolStatus.NOT_FOUND:
                return GroundedAgentResponse(
                    answer=f"Mình xác nhận đơn {order_id} tồn tại, nhưng chưa tìm thấy hành trình vận chuyển đang hoạt động. Mình chưa thể kết luận đơn đang ở đâu hoặc đơn vị nào đang giao. Bạn có thể thử lại sau; nếu đơn đã quá thời gian dự kiến, mình sẽ chuyển nhân viên kiểm tra.",
                    confidence=0.45,
                    tool_calls=calls,
                    missing_facts=["SHIPMENT"],
                    verified_facts=verified_facts("get_order_details", details, ("status", "updatedAt")),
                    customer_context_used=[CustomerContextUsed(type="ORDER", reference_id=order_id, observed_at=details.observed_at)],
                )
            status = STATUS_LABELS.get(str(data.get("status")), "đang được xử lý")
            eta = format_datetime(data.get("estimatedDelivery"))
            carrier = data.get("carrier") or "đơn vị vận chuyển"
            asks_recipient = any(term in normalized_content for term in ("giao cho ai", "ai nhận"))
            asks_location = any(term in normalized_content for term in ("giao nhầm đâu", "giao ở đâu", "địa chỉ nào"))
            missing_delivery = any(term in normalized_content for term in ("chưa nhận", "không thấy", "giao cho ai", "giao nhầm", "đã giao"))
            if str(data.get("status")) == "DELIVERED" and missing_delivery:
                unavailable = "Mình chưa thấy tên người nhận trong thông tin vận chuyển." if asks_recipient else "Mình chưa thấy địa điểm giao chi tiết trong thông tin vận chuyển." if asks_location else "Thông tin vận chuyển chưa ghi rõ người đã nhận hàng."
                answer = f"Đơn {order_id} đang báo đã giao thành công qua {carrier}. {unavailable} Bạn kiểm tra với người thân, lễ tân hoặc bảo vệ; nếu vẫn không có, mình có thể mở tra soát giao hàng ngay."
            else:
                delivered = str(data.get("status")) == "DELIVERED"
                out_for_delivery = str(data.get("status")) == "OUT_FOR_DELIVERY"
                if out_for_delivery:
                    answer = f"Có, shipper đã nhận đơn {order_id} và đang giao tới bạn. {carrier} đang phụ trách đơn"
                else:
                    answer = f"Đơn {order_id} {'đã giao rồi' if delivered else 'chưa giao xong và hiện ' + status}. {carrier} đang phụ trách đơn"
                answer += f", dự kiến giao trước {eta}." if eta else "."
                if "hôm nay" in normalize_support_text(content) and data.get("estimatedDelivery"):
                    estimated = datetime.fromisoformat(str(data["estimatedDelivery"]).replace("Z", "+00:00")).astimezone(VIETNAM_TZ).date()
                    today = datetime.now(VIETNAM_TZ).date()
                    answer += " Dự kiến đơn sẽ giao trong hôm nay." if estimated == today else f" Hiện đơn không được dự kiến giao hôm nay mà vào ngày {estimated.strftime('%d/%m/%Y')}."
                if any(term in normalize_support_text(content) for term in ("lâu", "chậm")):
                    answer += " Mình chưa thấy dữ liệu nêu nguyên nhân chậm cụ thể; nếu quá mốc dự kiến, mình sẽ hỗ trợ mở tra soát."
        elif intent == "PAYMENT_STATUS":
            if result.status == ToolStatus.NOT_FOUND:
                answer = f"Chưa tìm thấy giao dịch thanh toán của đơn {order_id}. Bạn kiểm tra lại phương thức thanh toán hoặc thử lại sau nhé."
            else:
                status = PAYMENT_LABELS.get(str(data.get("status")), "đang được kiểm tra")
                amount = format_money(data.get("amount"), str(data.get("currency") or "VND"))
                answer = f"Khoản thanh toán {amount} của đơn {order_id} {status}." if amount else f"Thanh toán của đơn {order_id} {status}."
        elif intent == "REFUND_STATUS":
            if result.status == ToolStatus.NOT_FOUND:
                answer = f"Đơn {order_id} chưa có yêu cầu hoàn tiền, nên hiện chưa có mốc thời gian nhận tiền. Thời gian xử lý chỉ bắt đầu sau khi yêu cầu trả hàng/hoàn tiền được tạo và tiếp nhận. Nếu bạn muốn bắt đầu yêu cầu, nói mình tình trạng sản phẩm để mình kiểm tra điều kiện và bước tiếp theo."
            else:
                status = REFUND_LABELS.get(str(data.get("status")), "đang được kiểm tra")
                amount = format_money(data.get("amount"))
                answer = f"Yêu cầu hoàn {amount} cho đơn {order_id} {status}." if amount else f"Yêu cầu hoàn tiền cho đơn {order_id} {status}."
        else:
            items = data.get("items", [])
            eligible = [item for item in items if item.get("decision") == "ELIGIBLE"]
            human = [item for item in items if item.get("decision") == "NEEDS_HUMAN"]
            if eligible:
                product_names = ", ".join(item.get("productName") for item in eligible if item.get("productName"))
                remaining = min((item.get("remainingDays") for item in eligible if isinstance(item.get("remainingDays"), int)), default=None)
                answer = f"Đơn {order_id} có {len(eligible)} sản phẩm{f' ({product_names})' if product_names else ''} đủ điều kiện gửi yêu cầu trả hàng"
                answer += f", còn {remaining} ngày để gửi yêu cầu." if remaining is not None else "."
                if self._return_reason(content) == "MISSING_ITEM":
                    answer += " Với trường hợp thiếu món, bạn chụp kiện hàng, nhãn vận chuyển và các món thực nhận; mình có thể tạo yêu cầu trả hàng/hoàn tiền sau khi bạn xác nhận."
                else:
                    answer += " Bạn chuẩn bị ảnh hoặc video thể hiện lỗi/sai hàng; mình có thể tạo yêu cầu sau khi bạn xác nhận."
            elif human:
                answer = f"Mình chưa đủ căn cứ để kết luận khả năng trả hàng của đơn {order_id}; trường hợp này cần nhân viên kiểm tra chính sách áp dụng."
            else:
                answer = f"Đơn {order_id} hiện chưa đáp ứng điều kiện trả hàng theo trạng thái và lý do bạn cung cấp."
            facts = [VerifiedFact(key="returnDecision", value=item.get("decision"), source="check_return_eligibility", reference_id=str(item.get("orderItemId")), observed_at=result.observed_at) for item in items]
            return GroundedAgentResponse(answer=answer, confidence=0.95 if eligible else 0.7, tool_calls=calls, verified_facts=facts, requires_human=bool(human), escalation_reason="RETURN_RULE_REVIEW" if human else None, customer_context_used=[CustomerContextUsed(type="ORDER", reference_id=order_id, observed_at=details.observed_at)])

        fact_keys = {
            "ORDER_TRACKING": ("status", "carrier", "trackingMasked", "estimatedDelivery", "observedAt"),
            "PAYMENT_STATUS": ("status", "amount", "currency", "provider", "observedAt"),
            "REFUND_STATUS": ("status", "amount", "reason", "observedAt", "referenceId"),
        }.get(intent, ())
        return GroundedAgentResponse(answer=answer, confidence=1, tool_calls=calls, verified_facts=verified_facts(specialized.__name__, result, fact_keys), customer_context_used=[CustomerContextUsed(type="ORDER", reference_id=order_id, observed_at=details.observed_at)])

    async def _cancellation(self, message: IncomingMessage, context: TrustedContext, order_id: str | None) -> GroundedAgentResponse:
        if not order_id:
            eligible = await find_eligible_orders(context.tool_context(), "CANCELLABLE")
            return self._order_selector(eligible, "Mình đã kiểm tra tài khoản. Các đơn còn có thể hủy nằm bên dưới; bạn chọn một đơn nhé.", cancellable_only=True, message=message, resume_intent="ORDER_CANCELLATION", tool_name="find_eligible_orders")
        details = await get_order_details(context.tool_context(), order_id)
        calls = [tool_summary("get_order_details", details)]
        if details.status != ToolStatus.SUCCESS or not details.data:
            return GroundedAgentResponse(answer=f"Mình chưa thể hủy đơn {order_id} vì tài khoản hiện tại không xác minh được quyền sở hữu đơn. Bạn kiểm tra lại mã đơn và đăng nhập đúng tài khoản đã mua; nếu vẫn không thấy, mình sẽ chuyển nhân viên kiểm tra mà không tiết lộ thông tin đơn.", confidence=0.2, tool_calls=calls, requires_human=details.status == ToolStatus.FORBIDDEN, escalation_reason=details.error_code)
        status = str(details.data.get("status") or "")
        label = STATUS_LABELS.get(status, status.lower())
        if status not in {"PENDING", "CONFIRMED", "PROCESSING"}:
            return GroundedAgentResponse(answer=f"Đơn {order_id} {label}, nên giờ không thể hủy trực tiếp nữa. Nếu bạn không muốn nhận hàng, mình có thể hướng dẫn phương án phù hợp với trạng thái hiện tại.", confidence=1, tool_calls=calls)
        token, expires_at = create_confirmation_token({"action": "CANCEL_ORDER", "tool": "cancel_order", "customerId": message.customer_id, "conversationId": message.conversation_id, "orderId": order_id, "reason": "CUSTOMER_REQUEST"})
        pending = PendingAgentAction(action="CANCEL_ORDER", tool="cancel_order", arguments={"orderId": order_id, "reason": "CUSTOMER_REQUEST"}, confirmation_token=token, expires_at=expires_at)
        component = AgentUiComponent(type="CONFIRMATION", id=f"confirm-cancel-{order_id}", title=f"Hủy đơn {order_id}?", description=f"Đơn hiện {label}. Hệ thống chỉ hủy sau khi bạn xác nhận.", confirm_label="Đồng ý hủy", cancel_label="Không hủy", bindings=[VerifiedDataBinding(type="ORDER", reference_id=order_id)], continuation_token=token, expires_at=expires_at, pending_action=pending)
        return GroundedAgentResponse(answer=f"Mình vừa kiểm tra đơn {order_id}: trạng thái hiện tại là {label}, nên hệ thống vẫn cho phép gửi lệnh hủy. Đơn chưa bị hủy; bạn bấm “Đồng ý hủy” bên dưới nếu muốn thực hiện.", confidence=1, tool_calls=calls, verified_facts=verified_facts("get_order_details", details, ("status", "updatedAt")), ui=[component], pending_action=pending, conversation_state="AWAITING_CONFIRMATION")

    def _order_selector(self, result: Any, answer: str, cancellable_only: bool = False, message: IncomingMessage | None = None, resume_intent: str = "ORDER_TRACKING", tool_name: str = "get_recent_orders") -> GroundedAgentResponse:
        orders = (result.data or {}).get("orders", []) if result.status == ToolStatus.SUCCESS else []
        if cancellable_only or resume_intent == "ORDER_CANCELLATION":
            orders = [order for order in orders if str(order.get("status")) in {"PENDING", "CONFIRMED", "PROCESSING"}]
        elif resume_intent == "ORDER_TRACKING":
            orders = [order for order in orders if str(order.get("status")) in {"CONFIRMED", "PROCESSING", "SHIPPED", "OUT_FOR_DELIVERY"}]
        elif resume_intent == "PAYMENT_STATUS":
            orders = [order for order in orders if str(order.get("status")) not in {"CANCELLED"}]
        elif resume_intent == "REFUND_STATUS":
            orders = [order for order in orders if str(order.get("status")) in {"DELIVERED", "CANCELLED"}]
        elif resume_intent == "RETURN_ELIGIBILITY":
            orders = [order for order in orders if str(order.get("status")) == "DELIVERED"]
        if not orders:
            return GroundedAgentResponse(answer="Mình đã kiểm tra tài khoản nhưng hiện không có đơn phù hợp với yêu cầu này.", confidence=1, tool_calls=[tool_summary(tool_name, result)])
        options = [AgentChoice(id=str(order["id"]), label=str(order["id"]), description=f"{STATUS_LABELS.get(str(order['status']), str(order['status']))} · {format_money(order['totalAmount'], str(order['currency']))}", value={"orderId": str(order["id"])}) for order in orders]
        token = None
        expires_at = None
        if message:
            token, expires_at = create_confirmation_token({"action": "SELECT_ORDER", "resumeIntent": resume_intent, "originalMessage": message.content, "customerId": message.customer_id, "conversationId": message.conversation_id, "allowedOrderIds": [option.id for option in options]})
        component = AgentUiComponent(type="ORDER_SELECTOR", id=f"order-selector-{message.message_id if message else 'lookup'}", title="Chọn đơn hàng", description="Chọn một đơn để mình kiểm tra thông tin mới nhất.", options=options, bindings=[VerifiedDataBinding(type="ORDER", reference_id=option.id) for option in options], continuation_token=token, expires_at=expires_at)
        if cancellable_only:
            order_summary = "; ".join(f"{option.label}: {option.description}" for option in options)
            natural_answer = f"Mình tìm thấy {len(options)} đơn hiện còn có thể hủy: {order_summary}. Bạn chọn đúng đơn bên dưới; mình sẽ hiện bước xác nhận trước khi hủy."
        else:
            natural_answer = answer
        return GroundedAgentResponse(answer=natural_answer, confidence=1, tool_calls=[tool_summary(tool_name, result)], ui=[component], conversation_state="AWAITING_INPUT")

    @staticmethod
    def _order_summary(result: Any) -> GroundedAgentResponse:
        data = result.data or {}
        total = int(data.get("total") or 0) if result.status == ToolStatus.SUCCESS else 0
        if not total:
            return GroundedAgentResponse(answer="Tài khoản này hiện chưa có đơn hàng nào.", confidence=1, intent="ACCOUNT_ORDERS", tool_calls=[tool_summary("get_order_summary", result)])
        counts = dict(data.get("byStatus") or {})
        breakdown = ", ".join(f"{count} đơn {STATUS_LABELS.get(status, status.lower())}" for status, count in counts.items())
        return GroundedAgentResponse(answer=f"Tài khoản của bạn có tổng cộng {total} đơn: {breakdown}.", confidence=1, intent="ACCOUNT_ORDERS", tool_calls=[tool_summary("get_order_summary", result)])

    async def resume_order_intent(self, intent: str, message: IncomingMessage, order_id: str) -> GroundedAgentResponse:
        context = TrustedContext.from_message(message)
        if intent == "ORDER_CANCELLATION":
            response = await self._cancellation(message, context, order_id)
        elif intent in {"ORDER_TRACKING", "PAYMENT_STATUS", "REFUND_STATUS", "RETURN_ELIGIBILITY"}:
            response = await self._transaction(intent, context, order_id, message.content, message)
        else:
            response = await self._transaction("ORDER_TRACKING", context, order_id, message.content, message)
        self._attach_context(response, intent, order_id, message)
        return response

    async def _product_discovery(self, message: IncomingMessage, context: TrustedContext) -> GroundedAgentResponse:
        text = message.content.casefold()
        categories = {"tai nghe": "AUDIO", "điện thoại": "MOBILE", "phụ kiện": "ACCESSORY", "gia dụng": "HOME", "mỹ phẩm": "BEAUTY", "thời trang": "FASHION", "mẹ và bé": "MOM_BABY", "thực phẩm": "GROCERY"}
        category = next((value for key, value in categories.items() if key in text), None)
        budget_match = re.search(r"(?:dưới|tối đa|khoảng)\s*([\d.,]+)\s*(triệu|tr|nghìn|k)?", text)
        max_price = None
        if budget_match:
            number = float(budget_match.group(1).replace(".", "").replace(",", "."))
            unit = budget_match.group(2) or ""
            max_price = number * (1_000_000 if unit in {"triệu", "tr"} else 1_000 if unit in {"nghìn", "k"} else 1)
        tool_context = context.tool_context()
        result = await search_products(tool_context, "", category, max_price, 6)
        products = (result.data or {}).get("products", [])
        if not products:
            return GroundedAgentResponse(answer="Mình chưa tìm thấy sản phẩm còn hàng phù hợp. Bạn thử đổi mức giá hoặc loại sản phẩm nhé.", confidence=1, tool_calls=[tool_summary("search_products", result)])
        options = [AgentChoice(id=str(product["id"]), label=str(product["name"]), description=f"{format_money(product['price'])} · {float(product['rating']):.1f}★ · còn {product['stock']}", value={"productId": str(product["id"])}) for product in products]
        token, expires_at = create_confirmation_token({"action": "SELECT_PRODUCT_FOR_PURCHASE", "customerId": message.customer_id, "conversationId": message.conversation_id, "allowedProductIds": [option.id for option in options]})
        component = AgentUiComponent(type="PRODUCT_SELECTOR", id=f"product-selector-{message.message_id}", title="Sản phẩm phù hợp", description="Chọn sản phẩm bạn muốn mua; mình sẽ hỏi số lượng, địa chỉ và cách thanh toán.", options=options, bindings=[VerifiedDataBinding(type="PRODUCT", reference_id=option.id) for option in options], continuation_token=token, expires_at=expires_at)
        return GroundedAgentResponse(answer=f"Mình chọn được {len(options)} sản phẩm còn hàng phù hợp nhất. Bạn xem giá và đánh giá rồi chọn một sản phẩm nhé.", confidence=1, intent="PRODUCT_DISCOVERY", tool_calls=[tool_summary("search_products", result)], ui=[component], conversation_state="AWAITING_INPUT")

    async def _knowledge_stream(self, message: IncomingMessage, intent: str, order_id: str | None, plan: CasePlan, proposition: str) -> AsyncIterator[tuple[str, Any]]:
        profile_terms = {
            "TECHNICAL_SUPPORT": ("ứng dụng", "app", "cập nhật", "thông báo", "bộ nhớ"),
            "ACCOUNT_SECURITY": ("tài khoản", "bảo mật", "otp", "đăng nhập", "mật khẩu"),
            "FRAUD_WARNING": ("lừa đảo", "an toàn", "chuyển tiền", "link", "giả mạo"),
            "VOUCHER": ("voucher", "mã giảm giá", "ưu đãi"),
            "PRIVACY": ("dữ liệu", "thông tin cá nhân", "bảo mật"),
        }.get(intent, ())
        yield "retrieving", {"profile": intent, "query": proposition}
        candidates = await retrieve(RetrievalRequest(query=proposition, locale=message.locale, visibility="CUSTOMER_AUTHENTICATED" if message.customer_id else "PUBLIC", limit=8, profile=intent))
        if profile_terms:
            candidates.sort(key=lambda item: (sum(term in f"{item.title} {item.section} {item.content}".casefold() for term in profile_terms), item.score), reverse=True)
        results = candidates[:6]
        yield "retrieval_completed", {"count": len(results), "documents": [item.document_id for item in results], "channels": sorted({channel for item in results for channel in item.retrieval_channels})}
        if not results:
            gap_id = await self._record_gap(proposition, "NO_RETRIEVAL_RESULT")
            response = GroundedAgentResponse(answer="Mình chưa tìm thấy tài liệu đang hiệu lực đủ để trả lời chính xác câu hỏi này. Bạn có thể cung cấp thêm chi tiết hoặc chuyển cho nhân viên hỗ trợ kiểm tra.", confidence=0.2, tool_calls=[ToolExecutionSummary(name="search_knowledge", status=ToolStatus.SUCCESS)], knowledge_gaps=[gap_id] if gap_id else [], requires_human=True, escalation_reason="INSUFFICIENT_EVIDENCE")
            async for item in self._emit(self._finalize(response, plan, message.content)):
                yield item
            return
        evidence = [{"documentId": item.document_id, "title": item.title, "documentSummary": item.parent_summary, "section": item.section, "content": item.content[:1400], "version": item.semantic_version, "channels": item.retrieval_channels} for item in results]
        memory_context = ((message.page_context or {}).get("memory") or {})
        context_digest = json.dumps(memory_context, ensure_ascii=False, default=str)[:6000]
        prompt = (
            "Trả lời câu hỏi chăm sóc khách hàng chỉ bằng tiếng Việt tự nhiên, ngắn và trực tiếp. "
            "Chỉ dùng EVIDENCE_JSON. Không nhắc tool, JSON, graph hoặc mã enum. Không tự thêm quyền lợi, thời hạn, số tiền. "
            "Nêu kết luận dễ hiểu ở câu đầu. Trả lời riêng từng ý nếu người dùng hỏi nhiều ý. "
            "Với câu hỏi 'trường hợp nào', tổng hợp tất cả trường hợp liên quan có trong evidence thay vì chỉ lấy một ví dụ. "
            "Với câu hỏi lỗi hoặc không thực hiện được, nêu nguyên nhân có trong evidence, các bước tự xử lý theo thứ tự, rồi điều kiện cần liên hệ hỗ trợ. "
            "Với chính sách quyền riêng tư hoặc điều khoản, tóm tắt phạm vi chính trước rồi mới hỏi người dùng muốn xem sâu phần nào. "
            "Không dùng các cụm hàn lâm như 'chưa đủ căn cứ', 'bằng chứng hiện có', 'dữ liệu hệ thống'; hãy nói 'mình chưa kiểm tra được thông tin này'. "
            "Không lặp câu hỏi, không dùng Markdown nếu không cần, không trộn bất kỳ ngôn ngữ nào khác. "
            "Bắt đầu ngay bằng kết luận và không thêm lời chào hoặc câu dẫn như 'Mình kiểm tra được'. "
            "Không dùng các từ evidence, context, retrieval hoặc dữ liệu nguồn. Nếu tài liệu chỉ trả lời được một phần, nói rõ phần đã xác nhận, phần chưa có, và một bước tiếp theo cụ thể.\n"
            "Trả lời đầy đủ mọi phần trong PROPOSITION. Nếu evidence không có chi tiết được hỏi, nói rõ giới hạn đó thay vì đổi sang chủ đề khác.\n"
            f"INTENT: {intent}\nPROPOSITION: {proposition}\nUSER_MESSAGE: {message.content}\nMEMORY_CONTEXT: {context_digest}\nEVIDENCE_JSON: {json.dumps(evidence, ensure_ascii=False)}"
        )
        answer = ""
        profile = "reasoning" if plan.complexity in {"COMPLEX", "HIGH_RISK"} or intent in {"PRIVACY", "ACCOUNT_SECURITY", "FRAUD_WARNING", "REFUND_POLICY", "RETURN_POLICY", "PAYMENT_POLICY", "SHIPPING_POLICY"} else "fast"
        async for chunk in configured_model(profile).astream([SystemMessage(content=load_system_prompt()), HumanMessage(content=prompt)]):
            content = chunk.content if isinstance(chunk.content, str) else ""
            if content:
                answer += content
                yield "token", content
        streamed_answer = answer.strip()
        answer = streamed_answer
        if not answer:
            answer = "Mình chưa thể tạo câu trả lời từ các tài liệu hiện có."
        answer = self._ensure_relevance(intent, answer)
        if answer != streamed_answer:
            suffix = answer[len(streamed_answer):]
            if suffix:
                yield "token", suffix
        citations = [Citation(document_id=item.document_id, title=item.title, section=item.section, version=item.semantic_version, effective_from=item.effective_from.date(), public_url=item.public_url, snippet=item.content[:500], score=item.score) for item in results if item.public_url][:4]
        mode = "FOLLOW_UP" if order_id and not ORDER_PATTERN.search(message.content) else "DOMAIN"
        gaps = []
        if "chưa kiểm tra được" in answer.casefold() or "chưa có" in answer.casefold():
            gap_id = await self._record_gap(proposition, "PARTIAL_ANSWER")
            if gap_id:
                gaps.append(gap_id)
        response = GroundedAgentResponse(answer=answer, confidence=min(1, max(item.score for item in results)), citations=citations, knowledge_gaps=gaps, tool_calls=[ToolExecutionSummary(name="search_knowledge", status=ToolStatus.SUCCESS)], intent=intent, conversation_mode=mode, resolved_context={"orderId": order_id} if order_id else {})
        yield "reviewing", {"checks": list(plan.mandatory_checks)}
        response = self._finalize(response, plan, message.content)
        yield "validation", {"status": "PASSED"}
        yield "done", response

    @staticmethod
    async def _emit(response: GroundedAgentResponse) -> AsyncIterator[tuple[str, Any]]:
        for token in re.findall(r"\S+\s*", response.answer):
            yield "token", token
            await asyncio.sleep(0)
        yield "done", response

    @staticmethod
    def _return_reason(content: str) -> str:
        text = content.casefold()
        if "sai hàng" in text:
            return "WRONG_ITEM"
        if "thiếu" in text:
            return "MISSING_ITEM"
        if "không giống" in text or "mô tả" in text:
            return "NOT_AS_DESCRIBED"
        if "đổi ý" in text:
            return "CHANGE_OF_MIND"
        return "DAMAGED"

    @staticmethod
    def _ensure_relevance(intent: str, answer: str) -> str:
        lowered = answer.casefold()
        required = {
            "PAYMENT_POLICY": ("thanh toán", "Bạn có thể kiểm tra phương thức thanh toán áp dụng ở bước đặt hàng."),
            "RETURN_POLICY": ("trả hàng", "Nếu sản phẩm không giống mô tả, bạn nên gửi yêu cầu trả hàng và kèm ảnh hoặc video làm bằng chứng."),
            "PRIVACY": ("dữ liệu", "Yêu cầu này liên quan đến dữ liệu và thông tin tài khoản của bạn."),
            "SHIPPING_POLICY": ("giao", "Bạn có thể kiểm tra hướng dẫn giao hàng và vận chuyển trong chi tiết đơn."),
            "TECHNICAL_SUPPORT": ("ứng dụng", "Nếu ứng dụng vẫn lỗi, hãy ghi lại mã lỗi và ảnh chụp màn hình."),
            "VOUCHER": ("voucher", "Điều kiện voucher phụ thuộc chương trình và trạng thái đơn hàng."),
        }.get(intent)
        if required and required[0] not in lowered:
            return f"{answer.rstrip()} {required[1]}"
        return answer

    @staticmethod
    def _attach_context(response: GroundedAgentResponse, intent: str, order_id: str | None, message: IncomingMessage) -> None:
        response.intent = intent
        response.conversation_mode = "FOLLOW_UP" if order_id and not ORDER_PATTERN.search(message.content) else "DOMAIN"
        response.resolved_context = {"orderId": order_id} if order_id else {}

    @staticmethod
    def _finalize(response: GroundedAgentResponse, plan: CasePlan, content: str) -> GroundedAgentResponse:
        response = enrich_advisor_response(response, plan)
        response = review_response(content, response)
        errors = validate_advisor_response(response, plan)
        if settings.harness_v3_enabled:
            verdict = review_grounded_response(response, plan.required_tools)
            response.review_status = verdict.status
            errors.extend(verdict.errors)
        if errors:
            response.requires_human = True
            response.escalation_reason = errors[0]
            response.case_state = "HANDOFF"
            response.confidence = min(response.confidence, 0.3)
        return response

    @staticmethod
    def _social_answer(content: str) -> str:
        text = content.casefold()
        if "cảm ơn" in text or "cám ơn" in text:
            return "Không có gì. Bạn cần kiểm tra thêm đơn hàng hay vấn đề nào khác cứ nhắn mình nhé."
        if "tạm biệt" in text or "bye" in text:
            return "Chào bạn nhé. Khi cần kiểm tra đơn hàng, thanh toán hoặc trả hàng, cứ quay lại nhắn mình."
        if "làm được gì" in text or "giúp gì" in text:
            return "Mình có thể kiểm tra đơn hàng, giao vận, thanh toán, hoàn tiền, voucher, trả hàng và các chính sách của shop. Bạn đang cần hỗ trợ việc gì?"
        return "Chào bạn, mình đây. Bạn muốn kiểm tra đơn hàng hay cần hỗ trợ vấn đề gì?"

    @staticmethod
    def _out_of_scope_answer(content: str) -> str:
        text = content.casefold()
        if "thời tiết" in text:
            return "Mình không xem được thời tiết. Phạm vi hỗ trợ của mình gồm tài khoản, sản phẩm, đơn hàng, thanh toán, vận chuyển, voucher và trả hàng trên hệ thống shop."
        if "code" in text or "lập trình" in text:
            return "Mình không hỗ trợ viết code hoặc tư vấn lập trình. Phạm vi của mình gồm tài khoản, sản phẩm, đơn hàng, thanh toán, vận chuyển, voucher, bảo mật và trả hàng trên hệ thống shop."
        if "chứng khoán" in text or "đầu tư" in text:
            return "Mình không tư vấn đầu tư. Mình chỉ hỗ trợ các vấn đề liên quan tài khoản và mua sắm trên hệ thống."
        if "toán" in text or "tích phân" in text:
            return "Mình không giải bài toán. Mình có thể giúp bạn về đơn hàng, thanh toán, giao hàng hoặc trả hàng."
        return "Mình chỉ hỗ trợ các vấn đề liên quan hệ thống shop. Nếu bạn cần kiểm tra đơn hàng, thanh toán hoặc giao hàng, cứ nói mình nhé."
