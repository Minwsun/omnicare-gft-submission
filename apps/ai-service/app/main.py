import json
import logging
import re
import time
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .config import settings
from .contracts import AgentChoice, AgentInteractionRequest, AgentUiComponent, ConfirmActionRequest, GroundedAgentResponse, IncomingMessage, PendingAgentAction, RetrievalRequest, RetrievalResult, ToolContext, VerifiedDataBinding
from .models import LLMUnavailableError, configured_model
from .omnicare_agent import OmniCareAgentRuntime
from .omnicare_agent.framework_runtime import LangChainAgentRuntime
from .omnicare_agent.confirmation import create_confirmation_token, verify_confirmation_token
from .repositories import repository
from .retrieval import clear_retrieval_cache, retrieve
from .tools import cancel_order, confirm_checkout, create_checkout_session, get_customer_addresses, get_order_details, quote_checkout, update_checkout
from .graphrag_worker import GraphRagWorker
from .triage import TriageResult, triage_request

logger = logging.getLogger(__name__)
background_tasks: set[asyncio.Task] = set()


class AdminAssistRequest(BaseModel):
    ticket_id: str
    category: str
    priority: str
    summary: str
    customer: dict | None = None
    order: dict | None = None
    conversation: list[dict] = Field(default_factory=list)
    memory: dict | None = None
    evidence: list[dict] = Field(default_factory=list)
    context_version: str | None = None


def schedule_background(coro) -> None:
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def persist_trace_safely(**payload) -> None:
    try:
        await repository.persist_ai_trace(**payload)
    except Exception:
        logger.exception("AI trace batch persist failed")


def apply_triage(response: GroundedAgentResponse, triage: TriageResult) -> GroundedAgentResponse:
    response.category = triage.category
    response.priority = triage.priority
    response.priority_reasons = triage.priority_reasons
    response.request_fingerprint = triage.request_fingerprint
    if response.intent == "HUMAN_REQUEST":
        response.handoff_requested = True
        response.handoff_confidence = max(response.handoff_confidence, response.confidence)
        response.requires_human = True
        response.escalation_reason = response.escalation_reason or "CUSTOMER_REQUEST"
    if triage.requires_human or response.requires_human:
        response.requires_human = True
        response.escalation_reason = response.escalation_reason or triage.escalation_reason
        response.resolution_status = "HANDOFF"
        response.case_state = "HANDOFF"
    return response


async def ensure_handoff(message: IncomingMessage, response: GroundedAgentResponse, triage: TriageResult) -> None:
    if not response.requires_human:
        return
    try:
        ticket_id = f"TCK-{triage.request_fingerprint}"
        duplicate = await repository.ticket_exists(ticket_id)
        await repository.create_handoff_ticket(
            ticket_id,
            message.customer_id,
            message.conversation_id,
            triage.order_id,
            triage.category,
            response.answer,
            triage.priority,
            {
                "requestFingerprint": triage.request_fingerprint,
                "duplicate": duplicate,
                "intent": response.intent,
                "confidence": response.confidence,
                "escalationReason": response.escalation_reason,
                "handoffRequested": response.handoff_requested,
                "handoffConfidence": response.handoff_confidence,
                "missingFacts": response.missing_facts,
                "citations": [item.model_dump(mode="json") for item in response.citations],
                "toolCalls": [item.model_dump(mode="json") for item in response.tool_calls],
                "resolvedContext": response.resolved_context,
            },
        )
        if duplicate:
            response.duplicate_of = ticket_id
    except Exception:
        logger.exception("Handoff ticket persistence failed")


class VisionImage(BaseModel):
    data_url: str = Field(min_length=32, max_length=15_000_000)
    file_name: str = Field(min_length=1, max_length=180)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]


class VisionAnalyzeRequest(BaseModel):
    images: list[VisionImage] = Field(min_length=1, max_length=5)
    message: str = Field(default="", max_length=8000)
    order_context: dict = Field(default_factory=dict)


class VisionAnalysis(BaseModel):
    image_type: str = "OTHER"
    quality: str = "UNKNOWN"
    ocr: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def vision_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        await checkpointer.setup()
        try:
            app.state.agent_runtime = LangChainAgentRuntime.create(checkpointer) if settings.langchain_agent_enabled else OmniCareAgentRuntime.create(checkpointer)
        except LLMUnavailableError:
            logger.warning("LLM provider is not configured; agent endpoints will return 503")
            app.state.agent_runtime = None
        worker = GraphRagWorker(repository)
        app.state.graphrag_worker = worker
        if settings.graphrag_worker_enabled:
            await worker.start()
        try:
            yield
        finally:
            if settings.graphrag_worker_enabled:
                await worker.stop()
    await repository.close()


app = FastAPI(title="OmniCare AI Service", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["*"], allow_headers=["*"])


def agent_runtime():
    runtime = getattr(app.state, "agent_runtime", None)
    if runtime is None:
        raise LLMUnavailableError("LLM provider is not configured")
    return runtime

TOOL_PROGRESS_STAGES = {
    "get_customer_profile": ("RESOLVING_CUSTOMER", "Đang xác minh thông tin tài khoản…"),
    "get_recent_orders": ("CHECKING_ORDER", "Đang kiểm tra các đơn hàng…"),
    "get_order_details": ("CHECKING_ORDER", "Đang kiểm tra đơn hàng…"),
    "get_shipping_status": ("CHECKING_SHIPMENT", "Đang xem hành trình giao hàng…"),
    "get_payment_status": ("CHECKING_PAYMENT", "Đang đối chiếu trạng thái thanh toán…"),
    "get_refund_status": ("CHECKING_REFUND", "Đang kiểm tra tiến trình hoàn tiền…"),
    "check_return_eligibility": ("CHECKING_ELIGIBILITY", "Đang kiểm tra điều kiện áp dụng…"),
    "search_products": ("SEARCHING_PRODUCTS", "Đang tìm sản phẩm phù hợp…"),
    "get_product_details": ("SEARCHING_PRODUCTS", "Đang kiểm tra thông tin sản phẩm…"),
    "quote_checkout": ("PREPARING_ACTION", "Đang chuẩn bị lựa chọn cho bạn…"),
    "search_knowledge": ("SEARCHING_KNOWLEDGE", "Đang tìm thông tin liên quan…"),
}


def progress_event(stage: str, label: str, status: str = "STARTED") -> str:
    return f"event: progress\ndata: {json.dumps({'stage': stage, 'label': label, 'status': status, 'startedAt': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)}\n\n"


def tool_progress(payload) -> tuple[str, str]:
    tools = payload.get("tools", []) if isinstance(payload, dict) else []
    for item in tools:
        name = item.get("name") if isinstance(item, dict) else item
        if name in TOOL_PROGRESS_STAGES:
            return TOOL_PROGRESS_STAGES[name]
    return "PREPARING_ACTION", "Đang xử lý thông tin cần thiết…"


@app.get("/health")
async def health() -> dict:
    try:
        await repository.connect()
        await repository.pool.fetchval("SELECT 1")
        database = "ok"
    except Exception:
        database = "unavailable"
    try:
        configured_model()
        llm = "ready"
    except LLMUnavailableError:
        llm = "unavailable"
    worker = getattr(app.state, "graphrag_worker", None)
    worker_status = {"enabled": False, "status": "disabled"}
    if settings.graphrag_worker_enabled and worker:
        try:
            worker_status = await worker.status()
        except Exception as error:
            worker_status = {"enabled": True, "status": "degraded", "lastError": str(error)[:500]}
    healthy = database == "ok" and llm == "ready" and worker_status["status"] in {"ready", "disabled"}
    return {"status": "ok" if healthy else "degraded", "service": "omnicare-ai", "database": database, "llm": llm, "model": settings.llm_model, "worker": worker_status}


@app.post("/retrieval/ingestion/wake")
async def retrieval_ingestion_wake() -> dict:
    worker = getattr(app.state, "graphrag_worker", None)
    if not settings.graphrag_worker_enabled or worker is None:
        raise HTTPException(status_code=503, detail="INGESTION_WORKER_DISABLED")
    worker.notify()
    return {"woken": True}


@app.post("/vision/analyze", response_model=list[VisionAnalysis])
async def vision_analyze(request: VisionAnalyzeRequest) -> list[VisionAnalysis]:
    system = (
        "Bạn phân tích ảnh bằng chứng cho chăm sóc khách hàng Omni. "
        "Chỉ mô tả điều nhìn thấy; không suy đoán nguyên nhân, không xác nhận gian lận, không duyệt hoàn tiền. "
        "OCR chỉ chép thông tin nhìn rõ. Trả JSON array, mỗi ảnh đúng một object gồm image_type, quality, ocr, observations, missing_evidence, limitations."
    )
    content = [{"type": "text", "text": f"Yêu cầu khách hàng: {request.message}\nNgữ cảnh đơn hàng: {json.dumps(request.order_context, ensure_ascii=False)}"}]
    for image in request.images:
        content.extend([
            {"type": "text", "text": f"Ảnh: {image.file_name}"},
            {"type": "image_url", "image_url": {"url": image.data_url, "detail": "low"}},
        ])
    try:
        response = await configured_model("fast").ainvoke([SystemMessage(content=system), HumanMessage(content=content)])
        raw = response.content if isinstance(response.content, str) else json.dumps(response.content, ensure_ascii=False)
        payload = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        if not isinstance(payload, list) or len(payload) != len(request.images):
            raise ValueError("VISION_RESPONSE_SHAPE_INVALID")
        return [VisionAnalysis.model_validate({
            **item,
            "ocr": vision_list(item.get("ocr")),
            "observations": vision_list(item.get("observations")),
            "missing_evidence": vision_list(item.get("missing_evidence")),
            "limitations": vision_list(item.get("limitations")),
        }) for item in payload if isinstance(item, dict)]
    except LLMUnavailableError as error:
        raise HTTPException(status_code=503, detail="LLM_PROVIDER_UNAVAILABLE") from error
    except Exception as error:
        logger.exception("Vision analysis failed")
        raise HTTPException(status_code=502, detail="VISION_ANALYSIS_FAILED") from error


@app.post("/admin/assist")
async def admin_assist(request: AdminAssistRequest) -> dict:
    system = (
        "Bạn là copilot cho nhân viên chăm sóc khách hàng Omni. "
        "Bạn đang hỗ trợ nhân viên tiếp tục đúng cuộc trò chuyện khách vừa trao đổi với Omni AI. "
        "Ưu tiên câu khách mới nhất, không chào lại, không hỏi lại dữ kiện đã có. Chỉ dùng dữ kiện được cung cấp; không tự tạo trạng thái giao dịch. "
        "Trả JSON gồm summary, missing_information, next_action, reply_options, warnings. "
        "reply_options có 3 câu trả lời tiếng Việt: tự nhiên và đồng cảm; ngắn gọn; hỏi đúng thông tin còn thiếu. Không hứa điều chưa xác minh."
    )
    context = request.model_dump_json(exclude_none=True)
    try:
        response = await configured_model("fast").ainvoke([SystemMessage(content=system), HumanMessage(content=context)])
        raw = response.content if isinstance(response.content, str) else json.dumps(response.content, ensure_ascii=False)
        payload = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        if not isinstance(payload, dict):
            raise ValueError("ADMIN_ASSIST_RESPONSE_INVALID")
        return {
            "summary": str(payload.get("summary") or request.summary),
            "missing_information": [str(item) for item in payload.get("missing_information", [])][:8],
            "next_action": str(payload.get("next_action") or "Kiểm tra thông tin và phản hồi khách hàng."),
            "reply_options": [str(item) for item in payload.get("reply_options", [])][:4],
            "warnings": [str(item) for item in payload.get("warnings", [])][:8],
            "contextVersion": request.context_version,
        }
    except LLMUnavailableError as error:
        raise HTTPException(status_code=503, detail="LLM_PROVIDER_UNAVAILABLE") from error
    except Exception as error:
        logger.exception("Admin assist failed")
        raise HTTPException(status_code=502, detail="ADMIN_ASSIST_FAILED") from error


@app.post("/agent/run", response_model=GroundedAgentResponse)
async def agent_run(message: IncomingMessage) -> GroundedAgentResponse:
    try:
        triage = triage_request(message.content, message.customer_id)
        if triage.is_spam:
            return apply_triage(GroundedAgentResponse(answer="Mình chỉ hỗ trợ các vấn đề liên quan đến tài khoản, đơn hàng, thanh toán, sản phẩm và dịch vụ Omni.", confidence=1, intent="SPAM", conversation_mode="OUT_OF_SCOPE"), triage)
        response = apply_triage(await agent_runtime().run(message), triage)
        await ensure_handoff(message, response, triage)
        return response
    except LLMUnavailableError as error:
        raise HTTPException(status_code=503, detail="LLM_PROVIDER_UNAVAILABLE") from error
    except Exception as error:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=503, detail="AGENT_RUN_FAILED") from error


@app.post("/agent/stream")
async def agent_stream(message: IncomingMessage) -> StreamingResponse:
    async def events():
        started_at = time.perf_counter()
        last_step_at = started_at
        run_id = f"airun_{uuid4().hex}" if settings.harness_v3_enabled else None
        trace_steps = []
        yield f"event: accepted\ndata: {json.dumps({'messageId': message.message_id, 'runId': run_id})}\n\n"
        yield progress_event("UNDERSTANDING", "Đang tìm hiểu yêu cầu của bạn…")
        try:
            triage = triage_request(message.content, message.customer_id)
            if triage.is_spam:
                response = apply_triage(GroundedAgentResponse(answer="Mình chỉ hỗ trợ các vấn đề liên quan đến tài khoản, đơn hàng, thanh toán, sản phẩm và dịch vụ Omni.", confidence=1, intent="SPAM", conversation_mode="OUT_OF_SCOPE", run_id=run_id), triage)
                yield f"event: token\ndata: {json.dumps({'token': response.answer}, ensure_ascii=False)}\n\n"
                yield f"event: metrics\ndata: {json.dumps({'ttftMs': 0, 'totalMs': round((time.perf_counter() - started_at) * 1000)}, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {response.model_dump_json()}\n\n"
                return
            first_token_ms = None
            async for event_type, payload in agent_runtime().stream(message):
                if event_type == "planning":
                    yield progress_event("PLANNING", "Đang chọn cách hỗ trợ phù hợp…")
                elif event_type == "tool_started":
                    stage, label = tool_progress(payload)
                    yield progress_event(stage, label)
                elif event_type == "retrieving":
                    yield progress_event("SEARCHING_KNOWLEDGE", "Đang tìm thông tin liên quan…")
                elif event_type == "retrieval_completed":
                    yield progress_event("COMPARING_POLICY", "Đang đối chiếu thông tin áp dụng…")
                elif event_type == "reviewing":
                    yield progress_event("REVIEWING", "Đang kiểm tra lại độ chính xác…")
                if event_type in {"understanding", "planning", "context_loaded", "model_selected", "model_escalated", "specialist_selected", "tool_policy", "tool_started", "tool_completed", "retrieving", "retrieval_completed", "reviewing", "validation"}:
                    now = time.perf_counter()
                    if run_id:
                        trace_steps.append({"name": event_type, "status": "COMPLETED", "latency_ms": round((now - last_step_at) * 1000), "summary": payload if isinstance(payload, dict) else {"value": str(payload)[:500]}})
                    last_step_at = now
                    yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue
                if event_type == "token":
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - started_at) * 1000)
                        yield progress_event("WRITING", "Đang soạn câu trả lời…")
                        yield f"event: response_started\ndata: {json.dumps({'startedAt': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)}\n\n"
                    yield f"event: token\ndata: {json.dumps({'token': payload}, ensure_ascii=False)}\n\n"
                    continue
                if event_type != "done":
                    yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue
                response = apply_triage(payload, triage)
                await ensure_handoff(message, response, triage)
                response.run_id = run_id
                if response.resolved_context:
                    yield f"event: context_resolved\ndata: {json.dumps(response.resolved_context, ensure_ascii=False)}\n\n"
                if response.order_choices:
                    yield f"event: order_choices\ndata: {json.dumps({'orders': [choice.model_dump(mode='json') for choice in response.order_choices]}, ensure_ascii=False)}\n\n"
                for component in response.ui:
                    yield f"event: ui_component\ndata: {component.model_dump_json()}\n\n"
                if response.clarification:
                    yield f"event: clarification_ready\ndata: {response.clarification.model_dump_json()}\n\n"
                yield f"event: metrics\ndata: {json.dumps({'ttftMs': first_token_ms, 'totalMs': round((time.perf_counter() - started_at) * 1000)}, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {response.model_dump_json()}\n\n"
                if run_id:
                    schedule_background(persist_trace_safely(
                        run_id=run_id,
                        conversation_id=message.conversation_id,
                        prompt_version=f"{settings.prompt_version}:{settings.harness_version}",
                        intent=response.intent,
                        confidence=response.confidence,
                        requires_human=response.requires_human,
                        steps=trace_steps,
                        tool_calls=[{"name": call.name, "status": call.status.value, "reference_id": call.reference_id} for call in response.tool_calls],
                        retrievals=[{"document_id": citation.document_id, "version": citation.version, "score": citation.score or 0} for citation in response.citations],
                    ))
        except LLMUnavailableError:
            yield progress_event("FAILED", "Chưa thể hoàn tất yêu cầu.", "FAILED")
            yield f"event: error\ndata: {json.dumps({'code': 'LLM_PROVIDER_UNAVAILABLE', 'handoff': True})}\n\n"
        except Exception:
            logger.exception("Agent stream failed")
            yield progress_event("FAILED", "Chưa thể hoàn tất yêu cầu.", "FAILED")
            yield f"event: error\ndata: {json.dumps({'code': 'AGENT_RUN_FAILED', 'handoff': True})}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/agent/confirm", response_model=GroundedAgentResponse)
async def agent_confirm(request: ConfirmActionRequest) -> GroundedAgentResponse:
    try:
        payload = verify_confirmation_token(request.confirmation_token)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if payload.get("customerId") != request.customer_id or payload.get("conversationId") != request.conversation_id:
        raise HTTPException(status_code=403, detail="CONFIRMATION_CONTEXT_MISMATCH")
    if payload.get("tool") != "cancel_order":
        raise HTTPException(status_code=400, detail="UNSUPPORTED_CONFIRMED_ACTION")
    context = ToolContext(request_id=f"confirm:{payload['orderId']}", conversation_id=request.conversation_id, customer_id=request.customer_id, idempotency_key=request.confirmation_token)
    result = await cancel_order(context, payload["orderId"], payload.get("reason", "CUSTOMER_REQUEST"))
    if result.status.value != "SUCCESS":
        return GroundedAgentResponse(answer=result.safe_message or "Chưa thể thực hiện yêu cầu hủy đơn.", confidence=0.3, requires_human=result.status.value == "FORBIDDEN", escalation_reason=result.error_code)
    return GroundedAgentResponse(answer=f"Đã hủy đơn {payload['orderId']}. Đơn sẽ không tiếp tục được xử lý.", confidence=1, actions=[{"type": "CANCEL_ORDER", "status": "COMPLETED", "reference_id": result.reference_id}], tool_calls=[{"name": "cancel_order", "status": "SUCCESS", "reference_id": result.reference_id}], conversation_state="COMPLETED")


@app.post("/agent/interactions", response_model=GroundedAgentResponse)
async def agent_interaction(request: AgentInteractionRequest) -> GroundedAgentResponse:
    try:
        payload = verify_confirmation_token(request.continuation_token)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if payload.get("customerId") != request.customer_id or payload.get("conversationId") != request.conversation_id:
        raise HTTPException(status_code=403, detail="INTERACTION_CONTEXT_MISMATCH")
    context = ToolContext(request_id=f"interaction:{request.interaction_id}", conversation_id=request.conversation_id, customer_id=request.customer_id, idempotency_key=request.continuation_token)
    action = payload.get("action")
    if action == "SELECT_PRODUCT_FOR_PURCHASE" and request.action == "SELECT":
        product_id = str(request.values.get("productId") or "")
        if product_id not in payload.get("allowedProductIds", []):
            raise HTTPException(status_code=400, detail="INVALID_INTERACTION_OPTION")
        checkout_id = f"checkout_{request.interaction_id}"
        result = await create_checkout_session(context, checkout_id, product_id, 1)
        if result.status.value != "SUCCESS":
            return GroundedAgentResponse(answer="Sản phẩm vừa hết hàng hoặc không còn khả dụng. Bạn chọn sản phẩm khác nhé.", confidence=1)
        token, expires_at = create_confirmation_token({"action": "SET_PURCHASE_QUANTITY", "customerId": request.customer_id, "conversationId": request.conversation_id, "checkoutId": checkout_id, "productId": product_id})
        component = AgentUiComponent(type="QUANTITY_SELECTOR", id=f"quantity-{checkout_id}", title="Chọn số lượng", description=f"{result.data['productName']} · còn {result.data['stock']} sản phẩm", fields=[{"id": "quantity", "type": "NUMBER", "label": "Số lượng", "required": True}], continuation_token=token, expires_at=expires_at)
        return GroundedAgentResponse(answer="Bạn muốn mua bao nhiêu sản phẩm?", confidence=1, intent="CHECKOUT", goal="CREATE_ORDER", resolved_context={"activeIntent": "CHECKOUT", "checkoutStage": "QUANTITY", "checkoutId": checkout_id, "productId": product_id}, collected_slots={"productId": product_id, "checkoutId": checkout_id}, missing_slots=["quantity", "addressId", "paymentMethod"], ui=[component], conversation_state="AWAITING_INPUT")
    if action == "SET_PURCHASE_QUANTITY" and request.action == "SUBMIT":
        try:
            quantity = int(request.values.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        result = await create_checkout_session(context, str(payload["checkoutId"]), str(payload["productId"]), quantity)
        if result.status.value != "SUCCESS":
            return GroundedAgentResponse(answer="Số lượng không hợp lệ hoặc vượt tồn kho. Bạn chọn lại giúp mình nhé.", confidence=1)
        addresses = await get_customer_addresses(context)
        options = [AgentChoice(id=str(item["id"]), label=str(item["label"]), description=f"{item['recipient']} · {item['line1']}, {item['city']}", value={"addressId": str(item["id"])}) for item in (addresses.data or {}).get("addresses", [])]
        token, expires_at = create_confirmation_token({"action": "SELECT_PURCHASE_ADDRESS", "customerId": request.customer_id, "conversationId": request.conversation_id, "checkoutId": payload["checkoutId"], "allowedAddressIds": [option.id for option in options]})
        return GroundedAgentResponse(answer=f"Đã chọn {quantity} sản phẩm. Bạn chọn địa chỉ giao hàng nhé.", confidence=1, intent="CHECKOUT", goal="CREATE_ORDER", resolved_context={"activeIntent": "CHECKOUT", "checkoutStage": "ADDRESS", "checkoutId": payload["checkoutId"], "productId": payload["productId"], "quantity": quantity}, collected_slots={"productId": payload["productId"], "checkoutId": payload["checkoutId"], "quantity": quantity}, missing_slots=["addressId", "paymentMethod"], ui=[AgentUiComponent(type="ADDRESS_SELECTOR", id=f"address-{payload['checkoutId']}", title="Chọn địa chỉ nhận hàng", options=options, continuation_token=token, expires_at=expires_at)], conversation_state="AWAITING_INPUT")
    if action == "SELECT_PURCHASE_ADDRESS" and request.action == "SELECT":
        address_id = str(request.values.get("addressId") or "")
        if address_id not in payload.get("allowedAddressIds", []):
            raise HTTPException(status_code=400, detail="INVALID_INTERACTION_OPTION")
        await update_checkout(context, str(payload["checkoutId"]), address_id=address_id)
        options = [AgentChoice(id="COD", label="Thanh toán khi nhận hàng", description="Không thu tiền trước", value={"paymentMethod": "COD"}), AgentChoice(id="ONLINE_SIMULATED", label="Thanh toán online mô phỏng", description="Không phát sinh giao dịch thật", value={"paymentMethod": "ONLINE_SIMULATED"})]
        token, expires_at = create_confirmation_token({"action": "SELECT_PAYMENT_METHOD", "customerId": request.customer_id, "conversationId": request.conversation_id, "checkoutId": payload["checkoutId"], "allowedPaymentMethods": [option.id for option in options]})
        return GroundedAgentResponse(answer="Địa chỉ đã được chọn. Bạn muốn thanh toán theo cách nào?", confidence=1, intent="CHECKOUT", goal="CREATE_ORDER", resolved_context={"activeIntent": "CHECKOUT", "checkoutStage": "PAYMENT", "checkoutId": payload["checkoutId"], "addressId": address_id}, collected_slots={"checkoutId": payload["checkoutId"], "addressId": address_id}, missing_slots=["paymentMethod"], ui=[AgentUiComponent(type="PAYMENT_METHOD_SELECTOR", id=f"payment-{payload['checkoutId']}", title="Chọn cách thanh toán", options=options, continuation_token=token, expires_at=expires_at)], conversation_state="AWAITING_INPUT")
    if action == "SELECT_PAYMENT_METHOD" and request.action == "SELECT":
        payment_method = str(request.values.get("paymentMethod") or "")
        if payment_method not in payload.get("allowedPaymentMethods", []):
            raise HTTPException(status_code=400, detail="INVALID_INTERACTION_OPTION")
        await update_checkout(context, str(payload["checkoutId"]), payment_method=payment_method)
        quote = await quote_checkout(context, str(payload["checkoutId"]))
        data = quote.data or {}
        token, expires_at = create_confirmation_token({"action": "CONFIRM_CHECKOUT", "customerId": request.customer_id, "conversationId": request.conversation_id, "checkoutId": payload["checkoutId"]})
        summary = f"{data.get('productName')} × {data.get('quantity')} · Tổng {float(data.get('totalAmount', 0)):,.0f}đ · {data.get('addressLabel')}, {data.get('line1')}, {data.get('city')} · {payment_method}"
        return GroundedAgentResponse(answer="Mình đã tính lại giá và tồn kho. Bạn kiểm tra lần cuối rồi bấm Đặt hàng nhé.", confidence=1, intent="CHECKOUT", goal="CREATE_ORDER", resolved_context={"activeIntent": "CHECKOUT", "checkoutStage": "CONFIRMATION", "checkoutId": payload["checkoutId"], "paymentMethod": payment_method}, collected_slots={"checkoutId": payload["checkoutId"], "paymentMethod": payment_method}, ui=[AgentUiComponent(type="CHECKOUT_SUMMARY", id=f"summary-{payload['checkoutId']}", title="Xác nhận đặt hàng", description=summary, confirm_label="Đặt hàng", cancel_label="Chưa đặt", continuation_token=token, expires_at=expires_at)], conversation_state="AWAITING_CONFIRMATION")
    if action == "CONFIRM_CHECKOUT" and request.action == "CONFIRM":
        result = await confirm_checkout(context, str(payload["checkoutId"]))
        if result.status.value != "SUCCESS":
            return GroundedAgentResponse(answer="Chưa thể tạo đơn vì giá, tồn kho hoặc thông tin checkout đã thay đổi. Bạn chọn lại sản phẩm nhé.", confidence=1)
        data = result.data or {}
        return GroundedAgentResponse(answer=f"Đặt hàng thành công. Mã đơn mới là {data.get('orderId')}. Tổng tiền {float(data.get('totalAmount', 0)):,.0f}đ; phương thức {data.get('paymentMethod')}.", confidence=1, intent="CHECKOUT", goal="CREATE_ORDER", resolved_context={"activeIntent": "ORDER_TRACKING", "checkoutStage": "COMPLETED", "checkoutId": payload["checkoutId"], "orderId": data.get("orderId")}, actions=[{"type": "CREATE_ORDER", "status": "COMPLETED", "reference_id": data.get("orderId")}], tool_calls=[{"name": "confirm_checkout", "status": "SUCCESS", "reference_id": data.get("orderId")}], conversation_state="COMPLETED")
    if action == "PROVIDE_CLARIFICATION" and request.action in {"SELECT", "SUBMIT"}:
        field = str(payload.get("field") or "")
        value = str(request.values.get(field) or request.values.get("optionId") or "")
        if field != "returnReason" or value not in payload.get("allowedValues", []):
            raise HTTPException(status_code=400, detail="INVALID_INTERACTION_OPTION")
        order_id = str(payload.get("orderId") or "")
        resume_intent = str(payload.get("resumeIntent") or "RETURN_ELIGIBILITY")
        message = IncomingMessage(
            message_id=f"interaction:{request.interaction_id}",
            content=f"Lý do trả hàng đã chọn: {value}. Tiếp tục yêu cầu ban đầu: {payload.get('originalMessage') or 'kiểm tra trả hàng'}",
            customer_id=request.customer_id,
            actor_role="CUSTOMER",
            channel="WEB",
            conversation_id=request.conversation_id,
            page_context={"orderId": order_id, "resumeIntent": resume_intent, "returnReason": value, "clarification": {"field": field, "value": value}},
        )
        return await agent_runtime().run(message)
    if request.action in {"REJECT", "CANCEL"}:
        return GroundedAgentResponse(answer="Được rồi, tôi sẽ không thực hiện thay đổi nào.", confidence=1, conversation_state="COMPLETED")
    if payload.get("action") == "CANCEL_ORDER" and request.action == "CONFIRM":
        context = ToolContext(request_id=f"interaction:{request.interaction_id}", conversation_id=request.conversation_id, customer_id=request.customer_id, idempotency_key=request.continuation_token)
        result = await cancel_order(context, str(payload["orderId"]), str(payload.get("reason") or "CUSTOMER_REQUEST"))
        if result.status.value != "SUCCESS":
            return GroundedAgentResponse(answer=result.safe_message or "Chưa thể thực hiện yêu cầu hủy đơn.", confidence=0.3, requires_human=result.status.value == "FORBIDDEN", escalation_reason=result.error_code)
        return GroundedAgentResponse(answer=f"Đã hủy đơn {payload['orderId']}. Đơn sẽ không tiếp tục được xử lý.", confidence=1, actions=[{"type": "CANCEL_ORDER", "status": "COMPLETED", "reference_id": result.reference_id}], tool_calls=[{"name": "cancel_order", "status": "SUCCESS", "reference_id": result.reference_id}], conversation_state="COMPLETED")
    if payload.get("action") != "SELECT_ORDER" or request.action != "SELECT":
        raise HTTPException(status_code=400, detail="UNSUPPORTED_INTERACTION")
    order_id = str(request.values.get("orderId") or "")
    if order_id not in payload.get("allowedOrderIds", []):
        raise HTTPException(status_code=400, detail="INVALID_INTERACTION_OPTION")
    resume_intent = str(payload.get("resumeIntent") or "ORDER_TRACKING")
    message = IncomingMessage(message_id=f"interaction:{request.interaction_id}", content=str(payload.get("originalMessage") or f"Kiểm tra đơn {order_id}"), customer_id=request.customer_id, actor_role="CUSTOMER", channel="WEB", conversation_id=request.conversation_id, page_context={"orderId": order_id})
    return await agent_runtime().resume_order_intent(resume_intent, message, order_id)


@app.post("/retrieval/search", response_model=list[RetrievalResult])
async def retrieval_search(request: RetrievalRequest) -> list[RetrievalResult]:
    return await retrieve(request)


@app.post("/retrieval/rebuild-all")
async def retrieval_rebuild_all() -> dict:
    result = await repository.rebuild_knowledge_graph()
    await clear_retrieval_cache()
    return result


@app.post("/retrieval/cache/clear")
async def retrieval_cache_clear() -> dict:
    await clear_retrieval_cache()
    return {"cleared": True}


