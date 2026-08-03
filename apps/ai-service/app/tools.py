import hashlib
from datetime import datetime, timezone
from typing import Optional

from .contracts import ToolContext, ToolResult, ToolStatus
from .repositories import Repository, repository, utc_now


def _result(status: ToolStatus, data=None, error_code=None, safe_message=None, reference_id=None) -> ToolResult:
    return ToolResult(status=status, data=data, error_code=error_code, safe_message=safe_message, observed_at=utc_now(), reference_id=reference_id)


def _action_id(context: ToolContext, action: str, order_id: str) -> Optional[str]:
    if not context.idempotency_key:
        return None
    digest = hashlib.sha256(f"{context.idempotency_key}:{action}:{order_id}".encode()).hexdigest()[:20]
    return f"act_{digest}"


async def get_customer_profile(context: ToolContext, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED", safe_message="Cần xác minh tài khoản trước khi tra cứu.")
    data = await store.customer_profile(context.customer_id)
    return _result(ToolStatus.SUCCESS, data) if data else _result(ToolStatus.NOT_FOUND, error_code="CUSTOMER_NOT_FOUND", safe_message="Không thể xác minh thông tin khách hàng.")


async def get_recent_orders(context: ToolContext, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED", safe_message="Cần xác minh tài khoản trước khi tra cứu đơn hàng.")
    return _result(ToolStatus.SUCCESS, {"orders": await store.recent_orders(context.customer_id)})


async def get_order_summary(context: ToolContext, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED", safe_message="Cần xác minh tài khoản trước khi tổng hợp đơn hàng.")
    return _result(ToolStatus.SUCCESS, await store.order_summary(context.customer_id))


async def find_eligible_orders(context: ToolContext, goal: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    statuses_by_goal = {
        "CANCELLABLE": ["PENDING", "CONFIRMED", "PROCESSING"],
        "IN_TRANSIT": ["CONFIRMED", "PROCESSING", "SHIPPED", "OUT_FOR_DELIVERY"],
        "PAYMENT_RELEVANT": ["PENDING", "CONFIRMED", "PROCESSING", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"],
        "REFUND_RELEVANT": ["DELIVERED", "CANCELLED"],
        "RETURNABLE": ["DELIVERED"],
    }
    statuses = statuses_by_goal.get(goal)
    if statuses is None:
        return _result(ToolStatus.INVALID_INPUT, error_code="UNKNOWN_ORDER_ELIGIBILITY_GOAL")
    orders = await store.orders_by_status(context.customer_id, statuses)
    return _result(ToolStatus.SUCCESS, {"orders": orders, "goal": goal, "selectionRequired": len(orders) > 1})


async def get_order_details(context: ToolContext, order_id: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    data = await store.order_details(context.customer_id, order_id)
    return _result(ToolStatus.SUCCESS, data) if data else _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE", safe_message="Không thể xác minh đơn hàng này.")


async def get_shipping_status(context: ToolContext, order_id: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    data = await store.shipment_status(context.customer_id, order_id)
    if not data:
        return _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE", safe_message="Không thể xác minh đơn hàng này.")
    if not data.get("id"):
        return _result(ToolStatus.NOT_FOUND, error_code="SHIPMENT_NOT_FOUND", safe_message="Đơn hàng chưa có thông tin vận chuyển.")
    return _result(ToolStatus.SUCCESS, data)


async def get_payment_status(context: ToolContext, order_id: str, store: Repository = repository) -> ToolResult:
    ownership = await get_order_details(context, order_id, store)
    if ownership.status != ToolStatus.SUCCESS:
        return ownership
    data = await store.payment_status(context.customer_id, order_id)
    return _result(ToolStatus.SUCCESS, data) if data else _result(ToolStatus.NOT_FOUND, error_code="PAYMENT_NOT_FOUND", safe_message="Chưa tìm thấy giao dịch thanh toán.")


async def get_refund_status(context: ToolContext, order_id: str, store: Repository = repository) -> ToolResult:
    ownership = await get_order_details(context, order_id, store)
    if ownership.status != ToolStatus.SUCCESS:
        return ownership
    data = await store.refund_status(context.customer_id, order_id)
    return _result(ToolStatus.SUCCESS, data) if data else _result(ToolStatus.NOT_FOUND, error_code="REFUND_NOT_FOUND", safe_message="Đơn hàng chưa có yêu cầu hoàn tiền.")


async def check_return_eligibility(context: ToolContext, order_id: str, reason_code: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    items = await store.return_context(context.customer_id, order_id)
    if not items:
        return _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE", safe_message="Không thể xác minh đơn hàng này.")
    normalized_reason = reason_code.upper()
    decisions = []
    for item in items:
        rule = await store.return_rule(item["category"], normalized_reason)
        if not rule:
            decisions.append({"orderItemId": item["orderItemId"], "decision": "NEEDS_HUMAN", "failedConditions": ["RETURN_RULE_NOT_FOUND"]})
            continue
        delivered_at = item.get("deliveredAt")
        if item["orderStatus"] != "DELIVERED" or delivered_at is None:
            decisions.append({"orderItemId": item["orderItemId"], "productName": item["productName"], "decision": "NOT_ELIGIBLE", "failedConditions": ["ORDER_NOT_DELIVERED"], "ruleId": rule["id"]})
            continue
        now = datetime.now(timezone.utc)
        delivered_at = delivered_at.replace(tzinfo=timezone.utc) if delivered_at.tzinfo is None else delivered_at
        elapsed_days = (now - delivered_at).days
        eligible = bool(rule["returnable"] and item.get("profileReturnable", True) and elapsed_days <= rule["windowDays"])
        decisions.append({
            "orderItemId": item["orderItemId"], "productId": item["productId"], "productName": item["productName"],
            "category": item["category"], "decision": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
            "windowDays": rule["windowDays"], "elapsedDays": elapsed_days,
            "remainingDays": max(0, rule["windowDays"] - elapsed_days),
            "requiredEvidence": rule["evidenceTypes"], "failedConditions": [] if eligible else ["RETURN_WINDOW_EXPIRED_OR_PROFILE_BLOCKED"],
            "ruleId": rule["id"], "policyDocumentId": rule["documentId"], "policyVersionId": rule["versionId"],
            "graphPath": [order_id, item["orderItemId"], item["productId"], item["category"], rule["id"], rule["documentId"]],
        })
    return _result(ToolStatus.SUCCESS, {"orderId": order_id, "reasonCode": normalized_reason, "items": decisions}, reference_id=order_id)


async def get_active_incidents(context: ToolContext, store: Repository = repository) -> ToolResult:
    incidents = await store.active_incidents()
    return _result(ToolStatus.SUCCESS, {"incidents": incidents})


async def create_support_ticket(context: ToolContext, category: str, summary: str, priority: str, order_id: Optional[str] = None, store: Repository = repository) -> ToolResult:
    if not context.idempotency_key:
        return _result(ToolStatus.INVALID_INPUT, error_code="IDEMPOTENCY_KEY_REQUIRED")
    digest = hashlib.sha256(context.idempotency_key.encode("utf-8")).hexdigest()[:12].upper()
    ticket_id = f"TCK-{digest}"
    await store.create_ticket(context.customer_id, context.conversation_id, order_id, category, summary, priority, ticket_id)
    return _result(ToolStatus.SUCCESS, {"ticket_id": ticket_id}, reference_id=ticket_id)


async def cancel_order(context: ToolContext, order_id: str, reason: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    action_id = _action_id(context, "CANCEL_ORDER", order_id)
    if not action_id:
        return _result(ToolStatus.INVALID_INPUT, error_code="IDEMPOTENCY_KEY_REQUIRED")
    data = await store.cancel_order(context.customer_id, context.conversation_id, order_id, reason, action_id)
    if not data:
        return _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE")
    if data.get("actionStatus") == "INVALID_STATE":
        return _result(ToolStatus.CONFLICT, data, "ORDER_NOT_CANCELLABLE", "Trạng thái hiện tại không cho phép hủy đơn.", order_id)
    return _result(ToolStatus.SUCCESS, data, reference_id=action_id)


async def create_return_request(context: ToolContext, order_id: str, reason_code: str, store: Repository = repository) -> ToolResult:
    eligibility = await check_return_eligibility(context, order_id, reason_code, store)
    if eligibility.status != ToolStatus.SUCCESS:
        return eligibility
    eligible_items = [item for item in eligibility.data.get("items", []) if item.get("decision") == "ELIGIBLE"]
    if not eligible_items:
        return _result(ToolStatus.CONFLICT, eligibility.data, "RETURN_NOT_ELIGIBLE", "Đơn hàng chưa đủ điều kiện tạo yêu cầu trả hàng.", order_id)
    action_id = _action_id(context, "CREATE_RETURN", order_id)
    if not action_id:
        return _result(ToolStatus.INVALID_INPUT, error_code="IDEMPOTENCY_KEY_REQUIRED")
    data = await store.create_commerce_action(context.customer_id, context.conversation_id, order_id, "CREATE_RETURN", {"reasonCode": reason_code, "items": [item["orderItemId"] for item in eligible_items]}, action_id, {"DELIVERED"})
    return _result(ToolStatus.SUCCESS, data, reference_id=action_id) if data and data.get("actionStatus") == "COMPLETED" else _result(ToolStatus.CONFLICT, data, "RETURN_INVALID_STATE")


async def create_shipping_investigation(context: ToolContext, order_id: str, issue: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    action_id = _action_id(context, "SHIPPING_INVESTIGATION", order_id)
    if not action_id:
        return _result(ToolStatus.INVALID_INPUT, error_code="IDEMPOTENCY_KEY_REQUIRED")
    data = await store.create_commerce_action(context.customer_id, context.conversation_id, order_id, "SHIPPING_INVESTIGATION", {"issue": issue}, action_id, {"SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"})
    if not data:
        return _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE")
    return _result(ToolStatus.SUCCESS, data, reference_id=action_id) if data.get("actionStatus") == "COMPLETED" else _result(ToolStatus.CONFLICT, data, "INVESTIGATION_INVALID_STATE")


async def create_dispute(context: ToolContext, order_id: str, reason: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    action_id = _action_id(context, "CREATE_DISPUTE", order_id)
    if not action_id:
        return _result(ToolStatus.INVALID_INPUT, error_code="IDEMPOTENCY_KEY_REQUIRED")
    data = await store.create_commerce_action(context.customer_id, context.conversation_id, order_id, "CREATE_DISPUTE", {"reason": reason}, action_id, {"DELIVERED", "CANCELLED"})
    if not data:
        return _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE")
    return _result(ToolStatus.SUCCESS, data, reference_id=action_id) if data.get("actionStatus") == "COMPLETED" else _result(ToolStatus.CONFLICT, data, "DISPUTE_INVALID_STATE")


async def create_refund(context: ToolContext, order_id: str, reason: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    action_id = _action_id(context, "CREATE_REFUND", order_id)
    if not action_id:
        return _result(ToolStatus.INVALID_INPUT, error_code="IDEMPOTENCY_KEY_REQUIRED")
    data = await store.create_refund(context.customer_id, context.conversation_id, order_id, reason, action_id)
    if not data:
        return _result(ToolStatus.FORBIDDEN, error_code="ORDER_NOT_ACCESSIBLE")
    return _result(ToolStatus.SUCCESS, data, reference_id=action_id) if data.get("actionStatus") == "COMPLETED" else _result(ToolStatus.CONFLICT, data, "REFUND_INVALID_STATE")


async def search_products(context: ToolContext, query: str = "", category: Optional[str] = None, max_price: Optional[float] = None, limit: int = 8, store: Repository = repository) -> ToolResult:
    rows = await store.search_products(query, category, max_price, limit)
    return _result(ToolStatus.SUCCESS, {"products": rows})


async def get_product_details(context: ToolContext, product_id: str, store: Repository = repository) -> ToolResult:
    row = await store.product_details(product_id)
    return _result(ToolStatus.SUCCESS, row) if row else _result(ToolStatus.NOT_FOUND, error_code="PRODUCT_NOT_FOUND")


async def get_customer_addresses(context: ToolContext, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    return _result(ToolStatus.SUCCESS, {"addresses": await store.customer_addresses(context.customer_id)})


async def create_checkout_session(context: ToolContext, checkout_id: str, product_id: str, quantity: int, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    data = await store.create_checkout_session(checkout_id, context.customer_id, context.conversation_id, product_id, quantity)
    return _result(ToolStatus.SUCCESS, data, reference_id=checkout_id) if data else _result(ToolStatus.CONFLICT, error_code="PRODUCT_OR_STOCK_INVALID")


async def update_checkout(context: ToolContext, checkout_id: str, address_id: Optional[str] = None, payment_method: Optional[str] = None, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    data = await store.update_checkout(checkout_id, context.customer_id, address_id, payment_method)
    return _result(ToolStatus.SUCCESS, data, reference_id=checkout_id) if data else _result(ToolStatus.CONFLICT, error_code="CHECKOUT_UPDATE_INVALID")


async def quote_checkout(context: ToolContext, checkout_id: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    data = await store.checkout_details(checkout_id, context.customer_id)
    return _result(ToolStatus.SUCCESS, data, reference_id=checkout_id) if data else _result(ToolStatus.NOT_FOUND, error_code="CHECKOUT_NOT_FOUND")


async def confirm_checkout(context: ToolContext, checkout_id: str, store: Repository = repository) -> ToolResult:
    if not context.customer_id:
        return _result(ToolStatus.FORBIDDEN, error_code="IDENTITY_REQUIRED")
    data = await store.confirm_checkout(checkout_id, context.customer_id)
    if not data:
        return _result(ToolStatus.NOT_FOUND, error_code="CHECKOUT_NOT_FOUND")
    return _result(ToolStatus.SUCCESS, data, reference_id=data.get("orderId")) if data.get("status") == "COMPLETED" else _result(ToolStatus.CONFLICT, data, data.get("status"))
