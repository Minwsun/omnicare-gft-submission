from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, AsyncIterator, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    PIIMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
    dynamic_prompt,
)
from langchain.agents.middleware import ModelRequest
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from ..config import settings
from ..contracts import AgentChoice, AgentUiComponent, Citation, ClarificationRequest, GroundedAgentResponse, IncomingMessage, RetrievalRequest, ToolExecutionSummary, ToolStatus, VerifiedDataBinding
from ..models import configured_model, load_system_prompt
from ..repositories import repository
from ..retrieval import retrieve
from ..tools import search_products as search_products_tool
from ..tool_adapters import bind_tool_context
from .confirmation import create_confirmation_token
from .context import TrustedContext
from .registry import ToolRegistry, tool_registry
from .runtime import PAYMENT_LABELS, REFUND_LABELS, STATUS_LABELS, classify, format_datetime, format_money, normalize_order_id, normalize_support_text
from ..tools import find_eligible_orders as find_eligible_orders_impl, get_order_details as get_order_details_impl, get_payment_status as get_payment_status_impl, get_refund_status as get_refund_status_impl, get_shipping_status as get_shipping_status_impl
from .supervisor import SupervisorHarness


class FrameworkCitation(BaseModel):
    document_id: str
    title: str
    section: str = "Nội dung liên quan"
    version: str
    effective_from: str
    public_url: str | None = None


class SupportAgentOutput(BaseModel):
    answer: str = Field(min_length=1)
    intent: str = "KNOWLEDGE"
    confidence: float = Field(default=0.8, ge=0, le=1)
    citations: list[FrameworkCitation] = Field(default_factory=list)
    requires_human: bool = False
    escalation_reason: str | None = None
    requested_action: Literal["NONE", "CANCEL_ORDER", "CREATE_RETURN_REQUEST", "CREATE_SHIPPING_INVESTIGATION", "CREATE_SUPPORT_TICKET"] = "NONE"
    requested_order_id: str | None = None


class SupportRuntimeContext(BaseModel):
    customer_id: str | None = None
    actor_role: str = "CUSTOMER"
    locale: str = "vi-VN"
    channel: str = "WEB"
    page_context: dict[str, Any] = Field(default_factory=dict)
    customer_profile: dict[str, Any] = Field(default_factory=dict)
    conversation_memory: dict[str, Any] = Field(default_factory=dict)
    memory_facts: list[dict[str, Any]] = Field(default_factory=list)
    open_tickets: list[dict[str, Any]] = Field(default_factory=list)
    active_incidents: list[dict[str, Any]] = Field(default_factory=list)
    loaded_at: str

    def compact_json(self) -> str:
        payload = {
            "identity": {"customerId": self.customer_id, "role": self.actor_role, "locale": self.locale, "channel": self.channel},
            "page": self.page_context,
            "profile": self.customer_profile,
            "conversation": self.conversation_memory,
            "memoryFacts": self.memory_facts[:8],
            "openTickets": self.open_tickets[:3],
            "activeIncidents": self.active_incidents[:3],
            "loadedAt": self.loaded_at,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


@dynamic_prompt
def support_dynamic_prompt(request: ModelRequest) -> str:
    context = request.runtime.context
    context_text = context.compact_json() if isinstance(context, SupportRuntimeContext) else "{}"
    return load_system_prompt() + (
        "\n\nRUNTIME CONTEXT do backend cung cấp, có độ tin cậy cao hơn USER_MESSAGE:\n"
        f"{context_text}\n\n"
        "Dùng context để hiểu câu nối tiếp và đối tượng đang được nói tới, nhưng trạng thái giao dịch có thể thay đổi nên phải gọi tool để xác minh trước khi khẳng định. "
        "Nếu người dùng phản biện câu trả lời trước về trạng thái đơn, bắt buộc gọi get_order_details và tool chuyên biệt liên quan trước khi xin lỗi/sửa câu trả lời. "
        "Nếu đang có yêu cầu chọn đơn chưa hoàn tất, hãy giữ nguyên goal và yêu cầu người dùng chọn thay vì đổi sang KNOWLEDGE. "
        "Chỉ trả lời tiếng Việt; không chèn từ thuộc bảng chữ cái khác. "
        "Nếu thiếu mã đơn, gọi find_eligible_orders. Nếu selectionRequired=true, dừng gọi tool theo từng order và yêu cầu khách chọn; backend tạo selector. "
        "Nếu page context có selected order, không gọi find_eligible_orders mà dùng đúng ID đó. Không gọi hàng loạt tool chi tiết cho nhiều đơn. "
        "Nếu nghiệp vụ cần trường bắt buộc chưa có, chỉ hỏi một thông tin có giá trị nhất ở lượt hiện tại. Không tự đoán lý do trả hàng, bằng chứng, số lượng, địa chỉ hoặc phương thức thanh toán. "
        "Nếu TRUSTED_BACKEND_CONTEXT có clarification_field và clarification_value, coi đó là lựa chọn đã được backend xác minh và tiếp tục goal cũ; không hỏi lại cùng field. "
        "Không tuyên bố đã thực hiện write action. Khi khách muốn hủy đơn, chỉ đặt requested_action=CANCEL_ORDER sau khi get_order_details xác nhận trạng thái cho phép. "
        "intent phải phản ánh nghiệp vụ thật, không dùng KNOWLEDGE sau khi gọi tool giao dịch."
    )


class LangChainAgentRuntime:
    RETURN_REASONS = {
        "DAMAGED": ("Hàng bị lỗi hoặc hư hỏng", "Sản phẩm vỡ, móp, không hoạt động hoặc có lỗi khi nhận."),
        "WRONG_ITEM": ("Giao sai sản phẩm", "Sản phẩm nhận được khác mẫu, loại hoặc phân loại đã đặt."),
        "MISSING_ITEM": ("Thiếu sản phẩm", "Kiện hàng thiếu món hoặc thiếu số lượng."),
        "NOT_AS_DESCRIBED": ("Không đúng mô tả", "Sản phẩm khác đáng kể so với thông tin bán hàng."),
        "CHANGE_OF_MIND": ("Đổi ý không còn nhu cầu", "Sản phẩm đúng nhưng bạn không còn muốn giữ."),
    }

    def __init__(self, registry: ToolRegistry, checkpointer=None) -> None:
        self.registry = registry
        self.read_tools = registry.read_tools()
        self.supervisor = SupervisorHarness(classify, normalize_support_text, normalize_order_id)
        fast_model = configured_model("fast")
        self.agent = create_agent(
            model=fast_model,
            tools=self.read_tools,
            system_prompt=None,
            middleware=[
                support_dynamic_prompt,
                ToolRetryMiddleware(max_retries=1, retry_on=(TimeoutError, ConnectionError), on_failure="continue", initial_delay=0.2, max_delay=1),
                ModelRetryMiddleware(max_retries=1, on_failure="continue", initial_delay=0.2, max_delay=1),
                ModelCallLimitMiddleware(run_limit=settings.agent_max_model_calls, exit_behavior="end"),
                ToolCallLimitMiddleware(run_limit=8, exit_behavior="continue"),
                ToolCallLimitMiddleware(tool_name="get_order_details", run_limit=1, exit_behavior="continue"),
                ToolCallLimitMiddleware(tool_name="get_shipping_status", run_limit=1, exit_behavior="continue"),
                ToolCallLimitMiddleware(tool_name="get_payment_status", run_limit=1, exit_behavior="continue"),
                ToolCallLimitMiddleware(tool_name="get_refund_status", run_limit=1, exit_behavior="continue"),
                ToolCallLimitMiddleware(tool_name="check_return_eligibility", run_limit=1, exit_behavior="continue"),
                PIIMiddleware("email", strategy="mask", apply_to_input=True, apply_to_output=True, apply_to_tool_results=True),
                PIIMiddleware("credit_card", strategy="mask", apply_to_input=True, apply_to_output=True, apply_to_tool_results=True),
            ],
            response_format=ToolStrategy(SupportAgentOutput),
            context_schema=SupportRuntimeContext,
            checkpointer=checkpointer,
            name="omnicare_customer_support",
        )

    @classmethod
    def create(cls, checkpointer=None, registry: ToolRegistry = tool_registry) -> "LangChainAgentRuntime":
        return cls(registry, checkpointer)

    async def run(self, message: IncomingMessage) -> GroundedAgentResponse:
        message = await self._prepare_message(message)
        context = TrustedContext.from_message(message)
        if self._semantic_intent(message) == "PRODUCT_DISCOVERY":
            return await self._run_product_discovery(message, context)
        if self._semantic_intent(message) == "ORDER_TRACKING":
            return await self._run_order_tracking_fast(message, context)
        if self._semantic_intent(message) == "ORDER_CANCELLATION":
            return await self._run_order_cancellation_fast(message, context)
        if self._semantic_intent(message) in {"PAYMENT_STATUS", "REFUND_STATUS"}:
            return await self._run_transaction_status_fast(message, context, self._semantic_intent(message))
        runtime_context = await self._load_runtime_context(message)
        config = {"configurable": {"thread_id": message.conversation_id}}
        with bind_tool_context(context.tool_context()):
            result = await self.agent.ainvoke({"messages": [HumanMessage(content=self._input_content(message))]}, config=config, context=runtime_context)
        return await self._ensure_grounded_citations(message, self._convert(message, result))

    async def stream(self, message: IncomingMessage) -> AsyncIterator[tuple[str, Any]]:
        message = await self._prepare_message(message)
        route = (message.page_context or {}).get("semanticRoute") or {}
        yield "understanding", {"framework": "langchain-create-agent", "fallback": False, "intent": route.get("primary_intent"), "confidence": route.get("confidence")}
        yield "planning", {"objective": route.get("proposition") or "FRAMEWORK_AGENT", "requiredTools": ((message.page_context or {}).get("semanticPlan") or {}).get("required_tools", [])}
        context = TrustedContext.from_message(message)
        if self._semantic_intent(message) == "PRODUCT_DISCOVERY":
            yield "tool_started", {"tools": ["search_products"]}
            response = await self._run_product_discovery(message, context)
            yield "tool_completed", {"tools": ["search_products"]}
            yield "token", response.answer
            yield "done", response
            return
        if self._semantic_intent(message) == "ORDER_TRACKING":
            yield "tool_started", {"tools": ["get_shipping_status" if normalize_order_id(message.content, message.page_context) else "find_eligible_orders"]}
            response = await self._run_order_tracking_fast(message, context)
            yield "tool_completed", {"tools": [call.name for call in response.tool_calls]}
            yield "token", response.answer
            yield "done", response
            return
        if self._semantic_intent(message) == "ORDER_CANCELLATION":
            yield "tool_started", {"tools": ["get_order_details" if normalize_order_id(message.content, message.page_context) else "find_eligible_orders"]}
            response = await self._run_order_cancellation_fast(message, context)
            yield "tool_completed", {"tools": [call.name for call in response.tool_calls]}
            yield "token", response.answer
            yield "done", response
            return
        if self._semantic_intent(message) in {"PAYMENT_STATUS", "REFUND_STATUS"}:
            intent = self._semantic_intent(message)
            yield "tool_started", {"tools": ["get_payment_status" if intent == "PAYMENT_STATUS" else "get_refund_status"]}
            response = await self._run_transaction_status_fast(message, context, intent)
            yield "tool_completed", {"tools": [call.name for call in response.tool_calls]}
            yield "token", response.answer
            yield "done", response
            return
        runtime_context = await self._load_runtime_context(message)
        yield "context_loaded", {"facts": len(runtime_context.memory_facts), "openTickets": len(runtime_context.open_tickets), "incidents": len(runtime_context.active_incidents), "activeContext": runtime_context.conversation_memory.get("activeContext", {})}
        config = {"configurable": {"thread_id": message.conversation_id}}
        started_tools: set[str] = set()
        streamed_answer: list[str] = []
        with bind_tool_context(context.tool_context()):
            async for event in self.agent.astream(
                {"messages": [HumanMessage(content=self._input_content(message))]},
                config=config,
                context=runtime_context,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                event_type = event.get("type")
                data = event.get("data")
                if event_type == "messages" and isinstance(data, tuple):
                    chunk = data[0]
                    if isinstance(chunk, AIMessageChunk):
                        for tool_call in chunk.tool_call_chunks:
                            name = str(tool_call.get("name") or "")
                            if name and name not in started_tools:
                                started_tools.add(name)
                                yield "tool_started", {"tools": [name]}
                        if isinstance(chunk.content, str) and chunk.content and not chunk.tool_call_chunks:
                            streamed_answer.append(chunk.content)
                            yield "token", chunk.content
                elif event_type == "updates" and isinstance(data, dict):
                    for update in data.values():
                        if not isinstance(update, dict):
                            continue
                        completed = [item.name for item in update.get("messages", []) if isinstance(item, ToolMessage) and item.name]
                        if completed:
                            yield "tool_completed", {"tools": completed}
        state = await self.agent.aget_state(config)
        response = await self._ensure_grounded_citations(message, self._convert(message, state.values))
        if streamed_answer:
            response.answer = "".join(streamed_answer)
        elif response.answer:
            yield "token", response.answer
        yield "done", response

    async def _prepare_message(self, message: IncomingMessage) -> IncomingMessage:
        prepared = await self.supervisor.prepare(message)
        route = prepared["route"]
        plan = prepared["plan"]
        deterministic_intent = classify(message.content)
        routed_intent = str(route.primary_intent)
        policy_intents = {"RETURN_POLICY", "REFUND_POLICY", "PAYMENT_POLICY", "SHIPPING_POLICY", "PRIVACY", "ACCOUNT_SECURITY", "FRAUD_WARNING", "TECHNICAL_SUPPORT", "VOUCHER"}
        if deterministic_intent in policy_intents and not normalize_order_id(message.content, message.page_context):
            route.primary_intent = deterministic_intent
        elif routed_intent == "PRODUCT_DISCOVERY" and deterministic_intent != "PRODUCT_DISCOVERY":
            route.primary_intent = deterministic_intent
        message.page_context = {
            **(message.page_context or {}),
            "semanticRoute": route.model_dump(mode="json"),
            "semanticEntities": prepared.get("semantic_entities") or {},
            "semanticPlan": {
                "objective": plan.objective,
                "required_tools": list(plan.required_tools),
                "required_facts": list(plan.required_facts),
            },
        }
        return message

    @staticmethod
    def _semantic_intent(message: IncomingMessage) -> str:
        route = (message.page_context or {}).get("semanticRoute")
        return str(route.get("primary_intent") or "") if isinstance(route, dict) else ""

    async def _run_product_discovery(self, message: IncomingMessage, context: TrustedContext) -> GroundedAgentResponse:
        page_context = message.page_context or {}
        entities = page_context.get("semanticEntities") if isinstance(page_context.get("semanticEntities"), dict) else {}
        query = next((str(entities.get(key) or "").strip() for key in ("product", "product_name", "category", "query", "need") if str(entities.get(key) or "").strip()), "")
        if not query:
            canonical = str(((page_context.get("semanticRoute") or {}).get("proposition") if isinstance(page_context.get("semanticRoute"), dict) else "") or message.content).strip()
            query = canonical if len(canonical.split()) <= 8 else message.content
        result = await search_products_tool(context.tool_context(), query, None, None, 6)
        payload = result.model_dump(mode="json")
        ui = self._product_selector(message, [("search_products", payload)], "PRODUCT_DISCOVERY")
        if not ui:
            return GroundedAgentResponse(
                answer="Mình chưa tìm thấy sản phẩm còn hàng phù hợp. Bạn cho mình tên sản phẩm, hãng hoặc khoảng giá cụ thể hơn nhé.",
                confidence=0.8,
                intent="PRODUCT_DISCOVERY",
                goal="FIND_PRODUCT",
                resolved_context={"activeIntent": "PRODUCT_DISCOVERY", "productQuery": query},
                tool_calls=[ToolExecutionSummary(name="search_products", status=result.status)],
            )
        return GroundedAgentResponse(
            answer="Mình đã tìm các sản phẩm còn hàng phù hợp. Bạn chọn một mẫu để tiếp tục nhé.",
            confidence=1,
            intent="PRODUCT_DISCOVERY",
            goal="CREATE_ORDER",
            resolved_context={"activeIntent": "PRODUCT_DISCOVERY", "productQuery": query},
            collected_slots={"productQuery": query},
            missing_slots=["productId", "quantity", "addressId", "paymentMethod"],
            tool_calls=[ToolExecutionSummary(name="search_products", status=result.status)],
            ui=ui,
            conversation_state="AWAITING_INPUT",
        )

    async def _run_order_tracking_fast(self, message: IncomingMessage, context: TrustedContext) -> GroundedAgentResponse:
        order_id = normalize_order_id(message.content, message.page_context)
        if not order_id:
            result = await find_eligible_orders_impl(context.tool_context(), "IN_TRANSIT")
            payload = result.model_dump(mode="json")
            orders = (result.data or {}).get("orders", []) if result.status == ToolStatus.SUCCESS else []
            if len(orders) == 1:
                order_id = str(orders[0]["id"])
            elif len(orders) > 1:
                ui = self._order_selector(message, [("find_eligible_orders", payload)], "ORDER_TRACKING")
                return GroundedAgentResponse(
                    answer="Mình đã tìm thấy các đơn đang được xử lý hoặc vận chuyển. Bạn chọn đúng đơn bên dưới để mình xem vị trí và thời gian giao mới nhất nhé.",
                    confidence=1,
                    intent="ORDER_TRACKING",
                    goal="ORDER_TRACKING",
                    tool_calls=[ToolExecutionSummary(name="find_eligible_orders", status=result.status)],
                    ui=ui,
                    conversation_state="AWAITING_INPUT",
                    resolution_status="NEEDS_INPUT",
                )
            else:
                return GroundedAgentResponse(
                    answer=result.safe_message or "Hiện tài khoản chưa có đơn nào đang được xử lý hoặc vận chuyển.",
                    confidence=1,
                    intent="ORDER_TRACKING",
                    goal="ORDER_TRACKING",
                    tool_calls=[ToolExecutionSummary(name="find_eligible_orders", status=result.status)],
                )
        shipping = await get_shipping_status_impl(context.tool_context(), order_id)
        if shipping.status == ToolStatus.FORBIDDEN:
            return GroundedAgentResponse(
                answer=shipping.safe_message or "Mình chưa thể xác minh đơn hàng này trong tài khoản của bạn.",
                confidence=0.2,
                intent="ORDER_TRACKING",
                goal="ORDER_TRACKING",
                requires_human=True,
                escalation_reason=shipping.error_code or "ORDER_OWNERSHIP_VERIFICATION_FAILED",
                tool_calls=[ToolExecutionSummary(name="get_shipping_status", status=shipping.status)],
            )
        if shipping.status != ToolStatus.SUCCESS:
            return GroundedAgentResponse(
                answer=shipping.safe_message or "Đơn chưa có thông tin vận chuyển mới.",
                confidence=0.8,
                intent="ORDER_TRACKING",
                goal="ORDER_TRACKING",
                resolved_context={"orderId": order_id},
                tool_calls=[ToolExecutionSummary(name="get_shipping_status", status=shipping.status)],
            )
        data = shipping.data or {}
        status = STATUS_LABELS.get(str(data.get("status")), str(data.get("status") or "đang được vận chuyển"))
        eta = format_datetime(data.get("estimatedDelivery"))
        carrier = str(data.get("carrier") or "đơn vị vận chuyển")
        normalized = normalize_support_text(message.content)
        delivery_dispute = any(term in normalized for term in ("chưa nhận", "không thấy", "giao nhầm", "giao cho ai"))
        if str(data.get("status")) == "DELIVERED" and delivery_dispute:
            return GroundedAgentResponse(
                answer=f"Đơn {order_id} đang được ghi nhận đã giao qua {carrier}, nhưng dữ liệu hiện có không cho biết chính xác ai đã nhận hoặc điểm giao chi tiết. Bạn kiểm tra với người thân, lễ tân hoặc bảo vệ; nếu vẫn chưa thấy hàng, mình sẽ chuyển yêu cầu tra soát giao hàng cho nhân viên hỗ trợ.",
                confidence=1,
                intent="ORDER_TRACKING",
                goal="DELIVERED_NOT_RECEIVED",
                resolved_context={"orderId": order_id, "deliveryIssue": "DELIVERED_NOT_RECEIVED"},
                requires_human=True,
                escalation_reason="DELIVERED_NOT_RECEIVED",
                tool_calls=[ToolExecutionSummary(name="get_shipping_status", status=shipping.status, reference_id=order_id)],
            )
        answer = f"Đơn {order_id} hiện {status} qua {carrier}."
        if eta and str(data.get("status")) != "DELIVERED":
            answer += f" Dự kiến giao trước {eta}."
        return GroundedAgentResponse(
            answer=answer,
            confidence=1,
            intent="ORDER_TRACKING",
            goal="ORDER_TRACKING",
            resolved_context={"orderId": order_id},
            tool_calls=[ToolExecutionSummary(name="get_shipping_status", status=shipping.status, reference_id=order_id)],
        )

    async def _run_transaction_status_fast(self, message: IncomingMessage, context: TrustedContext, intent: str) -> GroundedAgentResponse:
        order_id = normalize_order_id(message.content, message.page_context)
        goal = "PAYMENT_RELEVANT" if intent == "PAYMENT_STATUS" else "REFUND_RELEVANT"
        tool_name = "get_payment_status" if intent == "PAYMENT_STATUS" else "get_refund_status"
        if not order_id:
            result = await find_eligible_orders_impl(context.tool_context(), goal)
            payload = result.model_dump(mode="json")
            orders = (result.data or {}).get("orders", []) if result.status == ToolStatus.SUCCESS else []
            if len(orders) == 1:
                order_id = str(orders[0]["id"])
            elif len(orders) > 1:
                return GroundedAgentResponse(
                    answer="Mình đã tìm thấy nhiều đơn phù hợp. Bạn chọn đúng đơn bên dưới để mình kiểm tra giao dịch mới nhất nhé.",
                    confidence=1,
                    intent=intent,
                    goal=intent,
                    tool_calls=[ToolExecutionSummary(name="find_eligible_orders", status=result.status)],
                    ui=self._order_selector(message, [("find_eligible_orders", payload)], intent),
                    conversation_state="AWAITING_INPUT",
                    resolution_status="NEEDS_INPUT",
                )
            else:
                return GroundedAgentResponse(answer=result.safe_message or "Mình chưa tìm thấy đơn phù hợp trong tài khoản.", confidence=0.8, intent=intent, goal=intent, tool_calls=[ToolExecutionSummary(name="find_eligible_orders", status=result.status)])
        result = await (get_payment_status_impl(context.tool_context(), order_id) if intent == "PAYMENT_STATUS" else get_refund_status_impl(context.tool_context(), order_id))
        if result.status == ToolStatus.FORBIDDEN:
            return GroundedAgentResponse(answer=result.safe_message or "Mình không thể xác minh đơn hàng này trong tài khoản của bạn.", confidence=0.2, intent=intent, goal=intent, requires_human=True, escalation_reason=result.error_code or "ORDER_OWNERSHIP_VERIFICATION_FAILED", tool_calls=[ToolExecutionSummary(name=tool_name, status=result.status)])
        if result.status != ToolStatus.SUCCESS:
            return GroundedAgentResponse(answer=result.safe_message or "Mình chưa tìm thấy giao dịch phù hợp cho đơn này.", confidence=0.8, intent=intent, goal=intent, resolved_context={"orderId": order_id}, tool_calls=[ToolExecutionSummary(name=tool_name, status=result.status)])
        data = result.data or {}
        if intent == "PAYMENT_STATUS":
            status = PAYMENT_LABELS.get(str(data.get("status")), "đang được kiểm tra")
            amount = format_money(data.get("amount"), str(data.get("currency") or "VND"))
            answer = f"Khoản thanh toán {amount} của đơn {order_id} hiện {status}."
        else:
            status = REFUND_LABELS.get(str(data.get("status")), "đang được kiểm tra")
            amount = format_money(data.get("amount"), "VND")
            answer = f"Yêu cầu hoàn tiền {amount} của đơn {order_id} hiện {status}."
        return GroundedAgentResponse(answer=answer, confidence=1, intent=intent, goal=intent, resolved_context={"orderId": order_id}, tool_calls=[ToolExecutionSummary(name=tool_name, status=result.status, reference_id=order_id)])

    async def _run_order_cancellation_fast(self, message: IncomingMessage, context: TrustedContext) -> GroundedAgentResponse:
        order_id = normalize_order_id(message.content, message.page_context)
        if not order_id:
            result = await find_eligible_orders_impl(context.tool_context(), "CANCELLABLE")
            payload = result.model_dump(mode="json")
            orders = (result.data or {}).get("orders", []) if result.status == ToolStatus.SUCCESS else []
            if len(orders) == 1:
                order_id = str(orders[0]["id"])
            elif len(orders) > 1:
                return GroundedAgentResponse(
                    answer=f"Tài khoản của bạn có {len(orders)} đơn còn có thể yêu cầu hủy. Bạn chọn một đơn bên dưới để tiếp tục nhé.",
                    confidence=1,
                    intent="ORDER_CANCELLATION",
                    goal="ORDER_CANCELLATION",
                    tool_calls=[ToolExecutionSummary(name="find_eligible_orders", status=result.status)],
                    ui=self._order_selector(message, [("find_eligible_orders", payload)], "ORDER_CANCELLATION"),
                    conversation_state="AWAITING_INPUT",
                    resolution_status="NEEDS_INPUT",
                )
            else:
                return GroundedAgentResponse(
                    answer=result.safe_message or "Tài khoản của bạn hiện không có đơn nào còn có thể hủy.",
                    confidence=1,
                    intent="ORDER_CANCELLATION",
                    goal="ORDER_CANCELLATION",
                    tool_calls=[ToolExecutionSummary(name="find_eligible_orders", status=result.status)],
                )
        result = await get_order_details_impl(context.tool_context(), order_id)
        summary = ToolExecutionSummary(name="get_order_details", status=result.status, reference_id=order_id)
        if result.status == ToolStatus.FORBIDDEN:
            return GroundedAgentResponse(
                answer=f"Mình không thể xác minh đơn {order_id} trong tài khoản của bạn. Hãy kiểm tra lại mã đơn hoặc chọn đơn từ lịch sử mua hàng.",
                confidence=0.2,
                intent="ORDER_CANCELLATION",
                goal="ORDER_CANCELLATION",
                requires_human=True,
                escalation_reason=result.error_code or "ORDER_OWNERSHIP_VERIFICATION_FAILED",
                tool_calls=[summary],
            )
        if result.status != ToolStatus.SUCCESS:
            return GroundedAgentResponse(answer=result.safe_message or f"Mình chưa kiểm tra được đơn {order_id}.", confidence=0.5, intent="ORDER_CANCELLATION", goal="ORDER_CANCELLATION", tool_calls=[summary])
        data = result.data or {}
        raw_status = str(data.get("status") or "")
        status = STATUS_LABELS.get(raw_status, "đang được xử lý")
        if raw_status not in {"PENDING", "CONFIRMED", "PROCESSING"}:
            return GroundedAgentResponse(
                answer=f"Đơn {order_id} hiện {status}, nên không thể hủy ở giai đoạn này. Nếu hàng có vấn đề, mình có thể hỗ trợ kiểm tra đổi trả sau khi nhận hàng.",
                confidence=1,
                intent="ORDER_CANCELLATION",
                goal="ORDER_CANCELLATION",
                resolved_context={"orderId": order_id},
                tool_calls=[summary],
            )
        output = SupportAgentOutput(answer="Đơn có thể yêu cầu hủy.", intent="ORDER_CANCELLATION", requested_action="CANCEL_ORDER", requested_order_id=order_id)
        confirmation = self._confirmation(message, output)
        return GroundedAgentResponse(
            answer=f"Đơn {order_id} hiện {status} và vẫn có thể gửi yêu cầu hủy. Đơn chưa bị thay đổi; bạn chọn “Đồng ý hủy” bên dưới nếu muốn tiếp tục.",
            confidence=1,
            intent="ORDER_CANCELLATION",
            goal="ORDER_CANCELLATION",
            resolved_context={"orderId": order_id},
            tool_calls=[summary],
            ui=[confirmation] if confirmation else [],
            conversation_state="AWAITING_CONFIRMATION",
            resolution_status="READY_FOR_CONFIRMATION",
        )

    @staticmethod
    async def _load_runtime_context(message: IncomingMessage) -> SupportRuntimeContext:
        profile: dict[str, Any] = {}
        conversation: dict[str, Any] = {"memory": {}, "facts": [], "openTickets": []}
        incidents: list[dict[str, Any]] = []
        if message.customer_id:
            profile_result, conversation, incidents = await asyncio.gather(
                repository.customer_profile(message.customer_id),
                repository.conversation_context(message.conversation_id, message.customer_id),
                repository.active_incidents(),
            )
            profile = profile_result or {}
        return SupportRuntimeContext(
            customer_id=message.customer_id,
            actor_role=message.actor_role,
            locale=message.locale,
            channel=message.channel,
            page_context=message.page_context or {},
            customer_profile=profile,
            conversation_memory=conversation.get("memory") or {},
            memory_facts=conversation.get("facts") or [],
            open_tickets=conversation.get("openTickets") or [],
            active_incidents=incidents,
            loaded_at=datetime.utcnow().isoformat(),
        )

    async def resume_order_intent(self, intent: str, message: IncomingMessage, order_id: str) -> GroundedAgentResponse:
        message.page_context = {**(message.page_context or {}), "orderId": order_id, "resumeIntent": intent}
        return await self.run(message)

    def _convert(self, message: IncomingMessage, result: dict[str, Any]) -> GroundedAgentResponse:
        all_messages = result.get("messages", [])
        messages = self._current_turn_messages(all_messages)
        output = result.get("structured_response")
        if not isinstance(output, SupportAgentOutput):
            output = SupportAgentOutput(answer=self._last_answer(messages), confidence=0.5)
        tool_calls, tool_payloads = self._tool_results(messages)
        ownership_failure = next((payload for _, payload in tool_payloads if payload.get("error_code") == "ORDER_NOT_ACCESSIBLE"), None)
        if ownership_failure:
            output.requires_human = True
            output.escalation_reason = "ORDER_OWNERSHIP_VERIFICATION_FAILED"
        output.intent = self._infer_intent(output.intent, tool_payloads, tool_calls)
        output.intent = self._reconcile_text_intent(message, output.intent)
        if output.intent == "HUMAN_REQUEST":
            output.requires_human = True
            output.escalation_reason = output.escalation_reason or "CUSTOMER_REQUEST"
            output.answer = "Mình đang chuyển toàn bộ cuộc trò chuyện này đến nhân viên chăm sóc khách hàng. Bạn không cần trình bày lại từ đầu."
        self._infer_requested_action(message, output, tool_payloads)
        ui = self._order_selector(message, tool_payloads, output.intent)
        if not ui:
            ui = self._product_selector(message, tool_payloads, output.intent)
            if ui:
                output.intent = "PRODUCT_DISCOVERY"
                output.answer = "Mình đã tìm các sản phẩm còn hàng phù hợp. Bạn chọn một mẫu để tiếp tục chọn số lượng, địa chỉ và thanh toán nhé."
        if not ui and not normalize_order_id(message.content, message.page_context) and not self._historical_selected_order(all_messages):
            historical_calls, historical_payloads = self._tool_results(all_messages)
            pending_intent = self._infer_intent(output.intent, historical_payloads, historical_calls)
            ui = self._order_selector(message, historical_payloads, pending_intent)
            if ui:
                output.intent = pending_intent
        if ui and ui[0].type == "ORDER_SELECTOR":
            output.answer = "Mình đã kiểm tra các đơn phù hợp trong tài khoản. Bạn chọn đúng đơn bên dưới để mình tiếp tục nhé."
        clarification = None
        collected_slots: dict[str, Any] = {}
        missing_slots: list[str] = []
        if not ui:
            component, clarification, collected_slots = self._clarification_ui(message, all_messages, output.intent, tool_payloads)
            if component:
                ui.append(component)
                missing_slots = [clarification.field] if clarification else []
                output.answer = clarification.question if clarification else output.answer
        if output.requested_action != "NONE" and output.requested_order_id:
            confirmation = self._confirmation(message, output)
            if confirmation:
                ui.append(confirmation)
                output.answer = self._confirmation_answer(output, tool_payloads)
        citations = [
            {
                "document_id": item.document_id,
                "title": item.title,
                "section": item.section,
                "version": item.version,
                "effective_from": item.effective_from,
                "public_url": item.public_url,
            }
            for item in output.citations
        ]
        evidence_citations = self._citations_from_tools(tool_payloads)
        citations = list({(item["document_id"], item["version"]): item for item in [*evidence_citations, *citations]}.values())[:4]
        resolved_order_id = normalize_order_id(message.content, message.page_context) or self._historical_selected_order(all_messages)
        if not resolved_order_id:
            for _, payload in reversed(tool_payloads):
                if str(payload.get("status")) != "SUCCESS":
                    continue
                data = payload.get("data") or {}
                resolved_order_id = data.get("orderId") or data.get("id")
                if resolved_order_id:
                    break
        return GroundedAgentResponse(
            answer=self._sanitize_language(output.answer),
            confidence=output.confidence,
            intent=output.intent,
            goal=output.intent,
            resolved_context={"orderId": str(resolved_order_id)} if resolved_order_id else {},
            collected_slots=collected_slots,
            missing_slots=missing_slots,
            clarification=clarification,
            resolution_status="HANDOFF" if output.requires_human else "NEEDS_INPUT" if clarification else "READY_FOR_CONFIRMATION" if ui else "RESOLVED",
            next_best_action=clarification.question if clarification else None,
            citations=citations,
            tool_calls=tool_calls,
            ui=ui,
            requires_human=output.requires_human,
            escalation_reason=output.escalation_reason,
            conversation_state="AWAITING_INPUT" if ui else "ANSWERED",
            review_status="PASSED",
        )

    @staticmethod
    def _input_content(message: IncomingMessage) -> str:
        page_context = message.page_context or {}
        order_id = str(page_context.get("orderId") or "").strip()
        resume_intent = str(page_context.get("resumeIntent") or "").strip()
        semantic_route = page_context.get("semanticRoute") if isinstance(page_context.get("semanticRoute"), dict) else {}
        semantic_plan = page_context.get("semanticPlan") if isinstance(page_context.get("semanticPlan"), dict) else {}
        semantic_context = ""
        if semantic_route:
            semantic_context = (
                f"\nsemantic_intent={semantic_route.get('primary_intent', '')}"
                f"\ncanonical_request={semantic_route.get('proposition', '')}"
                f"\nrequired_tools={json.dumps(semantic_plan.get('required_tools', []), ensure_ascii=False)}"
            )
        attachments = page_context.get("attachments") if isinstance(page_context.get("attachments"), list) else []
        attachment_context = ""
        if attachments:
            evidence = [{
                "fileName": item.get("fileName"),
                "mimeType": item.get("mimeType"),
                "analysis": item.get("analysis"),
            } for item in attachments[:5] if isinstance(item, dict)]
            attachment_context = f"\nimage_evidence={json.dumps(evidence, ensure_ascii=False, default=str)}"
        clarification = page_context.get("clarification") if isinstance(page_context.get("clarification"), dict) else {}
        clarification_text = ""
        if clarification:
            clarification_text = f"\nclarification_field={clarification.get('field', '')}\nclarification_value={clarification.get('value', '')}"
        if order_id:
            return f"Người dùng đã chọn đơn {order_id}. Tiếp tục xử lý yêu cầu với đúng đơn này.\nYêu cầu hiện tại: {message.content}\n\n[TRUSTED_BACKEND_CONTEXT]\nselected_order_id={order_id}\nresume_intent={resume_intent}{clarification_text}{attachment_context}{semantic_context}"
        if attachment_context:
            return f"{message.content}\n\n[TRUSTED_BACKEND_CONTEXT]{attachment_context}{semantic_context}\nDùng image_evidence để trả lời về ảnh. Không khẳng định điều nằm ngoài observations/OCR; yêu cầu thêm ảnh nếu missing_evidence còn thiếu."
        if semantic_context:
            return f"{message.content}\n\n[TRUSTED_BACKEND_CONTEXT]{semantic_context}\nTuân theo semantic_intent. Gọi required_tools khi cần dữ liệu; không chuyển sang hồ sơ, KB hoặc intent khác nếu người dùng không yêu cầu."
        return message.content

    @staticmethod
    def _current_turn_messages(messages: list[Any]) -> list[Any]:
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                return messages[index:]
        return messages

    @staticmethod
    def _infer_intent(current: str, payloads: list[tuple[str, dict[str, Any]]], calls: list[ToolExecutionSummary]) -> str:
        names = {item.name for item in calls}
        if "get_order_summary" in names:
            return "ACCOUNT_ORDERS"
        for name, payload in reversed(payloads):
            if name == "find_eligible_orders":
                goal = str((payload.get("data") or {}).get("goal") or "")
                return {
                    "CANCELLABLE": "ORDER_CANCELLATION",
                    "IN_TRANSIT": "ORDER_TRACKING",
                    "PAYMENT_RELEVANT": "PAYMENT_STATUS",
                    "REFUND_RELEVANT": "REFUND_STATUS",
                    "RETURNABLE": "RETURN_ELIGIBILITY",
                }.get(goal, current)
        for tool_name, intent in (
            ("check_return_eligibility", "RETURN_ELIGIBILITY"),
            ("get_shipping_status", "ORDER_TRACKING"),
            ("get_payment_status", "PAYMENT_STATUS"),
            ("get_refund_status", "REFUND_STATUS"),
        ):
            if tool_name in names:
                return intent
        return current

    @staticmethod
    def _reconcile_text_intent(message: IncomingMessage, current: str) -> str:
        semantic_route = (message.page_context or {}).get("semanticRoute")
        if isinstance(semantic_route, dict):
            routed = str(semantic_route.get("primary_intent") or "")
            confidence = float(semantic_route.get("confidence") or 0)
            if routed and routed != "KNOWLEDGE" and confidence >= 0.55:
                return routed
        resume_intent = str((message.page_context or {}).get("resumeIntent") or "")
        if resume_intent in {
            "ORDER_CANCELLATION",
            "ORDER_TRACKING",
            "PAYMENT_STATUS",
            "REFUND_STATUS",
            "RETURN_ELIGIBILITY",
        }:
            return resume_intent
        if current not in {"KNOWLEDGE", "SOCIAL"}:
            return current
        inferred = classify(message.content)
        normalized = normalize_support_text(message.content)
        personal_policy_routes = {
            "RETURN_POLICY": ("RETURN_ELIGIBILITY", ("đơn này", "đơn của tôi", "tôi muốn trả", "trả đơn")),
            "SHIPPING_POLICY": ("ORDER_TRACKING", ("đơn này", "đơn của tôi", "giao chưa", "khi nào tới")),
            "REFUND_POLICY": ("REFUND_STATUS", ("đơn này", "đơn của tôi", "tiền về chưa", "hoàn cho đơn")),
            "PAYMENT_POLICY": ("PAYMENT_STATUS", ("đơn này", "đơn của tôi", "đã thanh toán", "đã trừ tiền")),
        }
        route = personal_policy_routes.get(inferred)
        if message.customer_id and route and any(term in normalized for term in route[1]):
            return route[0]
        return inferred if inferred != "KNOWLEDGE" else current

    @staticmethod
    def _product_selector(message: IncomingMessage, payloads: list[tuple[str, dict[str, Any]]], intent: str) -> list[AgentUiComponent]:
        if intent != "PRODUCT_DISCOVERY":
            return []
        for name, payload in reversed(payloads):
            if name != "search_products" or str(payload.get("status")) != "SUCCESS":
                continue
            products = ((payload.get("data") or {}).get("products") or [])
            options = [
                AgentChoice(
                    id=str(product.get("id")),
                    label=str(product.get("name") or product.get("id")),
                    description=f"{format_money(float(product.get('price') or 0))} · còn {int(product.get('stock') or 0)} sản phẩm",
                    value={"productId": str(product.get("id"))},
                )
                for product in products[:6]
                if product.get("id") and int(product.get("stock") or 0) > 0
            ]
            if not options:
                return []
            token, expires_at = create_confirmation_token({
                "action": "SELECT_PRODUCT_FOR_PURCHASE",
                "customerId": message.customer_id,
                "conversationId": message.conversation_id,
                "allowedProductIds": [option.id for option in options],
            })
            return [AgentUiComponent(
                type="PRODUCT_SELECTOR",
                id=f"product-selector-{message.message_id}",
                title="Chọn sản phẩm",
                description="Chọn đúng mẫu bạn muốn mua.",
                options=options,
                bindings=[VerifiedDataBinding(type="PRODUCT", reference_id=option.id) for option in options],
                continuation_token=token,
                expires_at=expires_at,
            )]
        return []

    @staticmethod
    def _historical_selected_order(messages: list[Any]) -> str | None:
        for item in reversed(messages):
            if not isinstance(item, HumanMessage) or not isinstance(item.content, str):
                continue
            match = re.search(r"selected_order_id=(ORD-[A-Z0-9]+)", item.content, flags=re.IGNORECASE)
            if match:
                return match.group(1).upper()
        return None

    @staticmethod
    def _sanitize_language(answer: str) -> str:
        words = answer.split()
        cleaned: list[str] = []
        for word in words:
            foreign_letter = any(
                unicodedata.category(character).startswith("L") and "LATIN" not in unicodedata.name(character, "")
                for character in word
            )
            if not foreign_letter:
                cleaned.append(word)
        return " ".join(cleaned).strip()

    @staticmethod
    def _infer_requested_action(message: IncomingMessage, output: SupportAgentOutput, payloads: list[tuple[str, dict[str, Any]]]) -> None:
        if output.requested_action != "NONE":
            return
        text = normalize_support_text(message.content)
        if not any(term in text for term in ("hủy", "không muốn mua", "dừng giao")):
            return
        order_id = normalize_order_id(message.content, message.page_context)
        if not order_id:
            return
        for name, payload in reversed(payloads):
            if name != "get_order_details" or str(payload.get("status")) != "SUCCESS":
                continue
            data = payload.get("data") or {}
            if str(data.get("id") or order_id) == order_id and str(data.get("status")) in {"PENDING", "CONFIRMED", "PROCESSING"}:
                output.requested_action = "CANCEL_ORDER"
                output.requested_order_id = order_id
                output.intent = "ORDER_CANCELLATION"
            return

    @staticmethod
    def _last_answer(messages: list[Any]) -> str:
        for item in reversed(messages):
            if isinstance(item, AIMessage) and item.content:
                answer = item.content if isinstance(item.content, str) else json.dumps(item.content, ensure_ascii=False)
                if "model call limits exceeded" in answer.casefold():
                    return "Mình đã kiểm tra nhưng chưa thể hoàn tất yêu cầu trong lượt này. Bạn chọn hoặc cung cấp thêm thông tin cụ thể để mình tiếp tục nhé."
                return answer
        return "Mình chưa thể hoàn tất yêu cầu này. Bạn thử diễn đạt lại ngắn gọn hơn nhé."

    @staticmethod
    def _tool_results(messages: list[Any]) -> tuple[list[ToolExecutionSummary], list[tuple[str, dict[str, Any]]]]:
        calls: list[ToolExecutionSummary] = []
        payloads: list[tuple[str, dict[str, Any]]] = []
        for item in messages:
            if not isinstance(item, ToolMessage):
                continue
            try:
                payload = json.loads(item.content) if isinstance(item.content, str) else item.content
            except (json.JSONDecodeError, TypeError):
                payload = {}
            status_value = str(payload.get("status") or "FAILED") if isinstance(payload, dict) else "FAILED"
            status = ToolStatus(status_value) if status_value in ToolStatus._value2member_map_ else ToolStatus.FAILED
            calls.append(ToolExecutionSummary(name=item.name or "unknown_tool", status=status, reference_id=payload.get("reference_id") if isinstance(payload, dict) else None))
            if isinstance(payload, dict):
                payloads.append((item.name or "unknown_tool", payload))
        return calls, payloads

    @staticmethod
    def _citations_from_tools(payloads: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for name, payload in payloads:
            if name != "search_knowledge" or str(payload.get("status")) != "SUCCESS":
                continue
            for item in ((payload.get("data") or {}).get("results") or []):
                if not isinstance(item, dict) or not item.get("document_id") or not item.get("semantic_version"):
                    continue
                effective_from = str(item.get("effective_from") or "").split("T", 1)[0]
                citations.append({
                    "document_id": str(item["document_id"]),
                    "title": str(item.get("title") or "Tài liệu hỗ trợ"),
                    "section": str(item.get("section") or "Nội dung liên quan"),
                    "version": str(item["semantic_version"]),
                    "effective_from": effective_from,
                    "public_url": item.get("public_url"),
                    "snippet": str(item.get("content") or "")[:500] or None,
                    "score": float(item.get("score") or 0),
                })
        return citations

    @staticmethod
    async def _ensure_grounded_citations(message: IncomingMessage, response: GroundedAgentResponse) -> GroundedAgentResponse:
        if response.citations or response.requires_human or response.intent not in {None, "KNOWLEDGE", "RETURN_POLICY", "REFUND_POLICY", "PAYMENT_POLICY", "SHIPPING_POLICY", "VOUCHER", "PRIVACY", "ACCOUNT_SECURITY", "FRAUD_WARNING", "TECHNICAL_SUPPORT"}:
            return response
        semantic_route = (message.page_context or {}).get("semanticRoute") or {}
        profile = response.intent or semantic_route.get("primary_intent")
        results = await retrieve(RetrievalRequest(query=message.content, locale=message.locale, visibility="CUSTOMER_AUTHENTICATED", profile=profile, limit=4))
        if not results:
            return response
        response.citations = [Citation(document_id=item.document_id, title=item.title, section=item.section, version=item.semantic_version, effective_from=item.effective_from.date(), public_url=item.public_url, snippet=item.content[:500], score=item.score) for item in results if item.public_url][:4]
        if response.citations and not any(call.name == "search_knowledge" for call in response.tool_calls):
            response.tool_calls.append(ToolExecutionSummary(name="search_knowledge", status=ToolStatus.SUCCESS))
        return response

    @staticmethod
    def _order_selector(message: IncomingMessage, payloads: list[tuple[str, dict[str, Any]]], intent: str) -> list[AgentUiComponent]:
        if normalize_order_id(message.content, message.page_context):
            return []
        for name, payload in reversed(payloads):
            if name not in {"find_eligible_orders", "get_recent_orders"}:
                continue
            orders = ((payload.get("data") or {}).get("orders") or [])
            if len(orders) <= 1:
                return []
            options = [AgentChoice(id=str(order["id"]), label=str(order["id"]), description=f"{STATUS_LABELS.get(str(order.get('status')), str(order.get('status')))} · {format_money(order.get('totalAmount'), str(order.get('currency') or 'VND'))}", value={"orderId": str(order["id"])}) for order in orders[:8]]
            token, expires_at = create_confirmation_token({"action": "SELECT_ORDER", "resumeIntent": intent, "originalMessage": message.content, "customerId": message.customer_id, "conversationId": message.conversation_id, "allowedOrderIds": [option.id for option in options]})
            return [AgentUiComponent(type="ORDER_SELECTOR", id=f"framework-order-selector-{message.message_id}", title="Chọn đơn hàng", description="Chọn một đơn để mình kiểm tra thông tin mới nhất.", options=options, bindings=[VerifiedDataBinding(type="ORDER", reference_id=option.id) for option in options], continuation_token=token, expires_at=expires_at)]
        return []

    @classmethod
    def _clarification_ui(
        cls,
        message: IncomingMessage,
        messages: list[Any],
        intent: str,
        payloads: list[tuple[str, dict[str, Any]]],
    ) -> tuple[AgentUiComponent | None, ClarificationRequest | None, dict[str, Any]]:
        if intent != "RETURN_ELIGIBILITY" or any(name == "check_return_eligibility" for name, _ in payloads):
            return None, None, {}
        order_id = normalize_order_id(message.content, message.page_context) or cls._historical_selected_order(messages)
        if not order_id:
            return None, None, {}
        reason_code = cls._return_reason(message, messages)
        if reason_code:
            return None, None, {"orderId": order_id, "returnReason": reason_code}
        options = [
            AgentChoice(id=code, label=label, description=description, value={"returnReason": code, "orderId": order_id})
            for code, (label, description) in cls.RETURN_REASONS.items()
        ]
        question = f"Bạn muốn trả đơn {order_id} vì lý do nào? Mình cần lý do để kiểm tra đúng điều kiện áp dụng."
        clarification = ClarificationRequest(
            reason="MISSING_REQUIRED_FIELD",
            field="returnReason",
            question=question,
            ui_type="SINGLE_CHOICE",
            suggested_options=[option.label for option in options],
        )
        token, expires_at = create_confirmation_token({
            "action": "PROVIDE_CLARIFICATION",
            "field": "returnReason",
            "customerId": message.customer_id,
            "conversationId": message.conversation_id,
            "orderId": order_id,
            "resumeIntent": intent,
            "originalMessage": message.content,
            "allowedValues": list(cls.RETURN_REASONS),
        })
        component = AgentUiComponent(
            type="SINGLE_CHOICE",
            id=f"clarify-return-reason-{message.message_id}",
            title="Lý do trả hàng",
            description="Chọn lý do gần đúng nhất. Bạn vẫn có thể mô tả thêm bằng tin nhắn.",
            options=options,
            bindings=[VerifiedDataBinding(type="ORDER", reference_id=order_id)],
            continuation_token=token,
            expires_at=expires_at,
        )
        return component, clarification, {"orderId": order_id}

    @classmethod
    def _return_reason(cls, message: IncomingMessage, messages: list[Any]) -> str | None:
        page_context = message.page_context or {}
        explicit = str(page_context.get("returnReason") or ((page_context.get("clarification") or {}).get("value") if isinstance(page_context.get("clarification"), dict) else ""))
        if explicit in cls.RETURN_REASONS:
            return explicit
        text_parts = [message.content]
        text_parts.extend(item.content for item in messages[-8:] if isinstance(item, HumanMessage) and isinstance(item.content, str))
        text = normalize_support_text(" ".join(text_parts))
        patterns = {
            "DAMAGED": ("hư", "hỏng", "bể", "vỡ", "móp", "không hoạt động", "lỗi"),
            "WRONG_ITEM": ("giao sai", "sai sản phẩm", "sai mẫu", "sai màu", "sai loại"),
            "MISSING_ITEM": ("thiếu hàng", "thiếu sản phẩm", "thiếu món", "thiếu số lượng"),
            "NOT_AS_DESCRIBED": ("không đúng mô tả", "khác mô tả", "không giống hình"),
            "CHANGE_OF_MIND": ("đổi ý", "không còn nhu cầu", "không muốn mua", "không thích"),
        }
        for code, terms in patterns.items():
            if any(term in text for term in terms):
                return code
        return None

    @staticmethod
    def _confirmation(message: IncomingMessage, output: SupportAgentOutput) -> AgentUiComponent | None:
        if output.requested_action != "CANCEL_ORDER":
            return None
        token, expires_at = create_confirmation_token({"action": "CANCEL_ORDER", "tool": "cancel_order", "customerId": message.customer_id, "conversationId": message.conversation_id, "orderId": output.requested_order_id, "reason": "CUSTOMER_REQUEST"})
        return AgentUiComponent(type="CONFIRMATION", id=f"framework-confirm-cancel-{output.requested_order_id}", title=f"Hủy đơn {output.requested_order_id}?", description="Đơn chỉ được hủy sau khi bạn xác nhận.", confirm_label="Đồng ý hủy", cancel_label="Không hủy", bindings=[VerifiedDataBinding(type="ORDER", reference_id=output.requested_order_id)], continuation_token=token, expires_at=expires_at)

    @staticmethod
    def _confirmation_answer(output: SupportAgentOutput, payloads: list[tuple[str, dict[str, Any]]]) -> str:
        for name, payload in reversed(payloads):
            if name != "get_order_details" or str(payload.get("status")) != "SUCCESS":
                continue
            data = payload.get("data") or {}
            status = STATUS_LABELS.get(str(data.get("status")), str(data.get("status") or "đang được xử lý"))
            return f"Mình vừa kiểm tra đơn {output.requested_order_id}: hiện {status} và vẫn có thể gửi yêu cầu hủy. Đơn chưa bị hủy; bạn bấm “Đồng ý hủy” bên dưới nếu muốn tiếp tục."
        return f"Đơn {output.requested_order_id} chưa bị thay đổi. Bạn bấm nút xác nhận bên dưới nếu muốn tiếp tục."
