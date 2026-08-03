from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Optional

from langchain.tools import tool

from .contracts import RetrievalRequest, ToolContext
from .retrieval import retrieve
from .tools import (
    cancel_order as cancel_order_impl,
    create_dispute as create_dispute_impl,
    create_refund as create_refund_impl,
    create_return_request as create_return_request_impl,
    create_shipping_investigation as create_shipping_investigation_impl,
    create_support_ticket as create_support_ticket_impl,
    get_active_incidents as get_active_incidents_impl,
    get_customer_profile as get_customer_profile_impl,
    get_order_details as get_order_details_impl,
    get_order_summary as get_order_summary_impl,
    find_eligible_orders as find_eligible_orders_impl,
    get_payment_status as get_payment_status_impl,
    get_recent_orders as get_recent_orders_impl,
    get_refund_status as get_refund_status_impl,
    check_return_eligibility as check_return_eligibility_impl,
    get_shipping_status as get_shipping_status_impl,
    search_products as search_products_impl,
    get_product_details as get_product_details_impl,
    get_customer_addresses as get_customer_addresses_impl,
    quote_checkout as quote_checkout_impl,
    create_checkout_session as create_checkout_session_impl,
    confirm_checkout as confirm_checkout_impl,
)


_runtime_context: ContextVar[Optional[ToolContext]] = ContextVar("omnicare_tool_context", default=None)


def trusted_context() -> ToolContext:
    context = _runtime_context.get()
    if context is None:
        raise RuntimeError("Trusted tool context is not available")
    return context


@contextmanager
def bind_tool_context(context: ToolContext):
    token = _runtime_context.set(context)
    try:
        yield
    finally:
        _runtime_context.reset(token)


@tool
async def get_customer_profile() -> dict:
    """Get the authenticated customer's masked profile."""
    return (await get_customer_profile_impl(trusted_context())).model_dump(mode="json")


@tool
async def get_recent_orders() -> dict:
    """List recent orders owned by the authenticated customer when no order ID is known."""
    return (await get_recent_orders_impl(trusted_context())).model_dump(mode="json")


@tool
async def get_order_summary() -> dict:
    """Count all orders owned by the authenticated customer and group them by current status."""
    return (await get_order_summary_impl(trusted_context())).model_dump(mode="json")


@tool
async def find_eligible_orders(goal: Literal["CANCELLABLE", "IN_TRANSIT", "PAYMENT_RELEVANT", "REFUND_RELEVANT", "RETURNABLE"]) -> dict:
    """Find owned orders relevant to a goal. If selectionRequired is true, stop calling order-specific tools and ask the customer to select one order."""
    return (await find_eligible_orders_impl(trusted_context(), goal)).model_dump(mode="json")


@tool
async def get_order_details(order_id: str) -> dict:
    """Get verified order facts after ownership validation."""
    return (await get_order_details_impl(trusted_context(), order_id)).model_dump(mode="json")


@tool
async def get_shipping_status(order_id: str) -> dict:
    """Get current shipping status and estimated delivery for an owned order."""
    return (await get_shipping_status_impl(trusted_context(), order_id)).model_dump(mode="json")


@tool
async def get_payment_status(order_id: str) -> dict:
    """Get current masked payment status for an owned order."""
    return (await get_payment_status_impl(trusted_context(), order_id)).model_dump(mode="json")


@tool
async def get_refund_status(order_id: str) -> dict:
    """Get current refund request status for an owned order."""
    return (await get_refund_status_impl(trusted_context(), order_id)).model_dump(mode="json")


@tool
async def check_return_eligibility(order_id: str, reason_code: Literal["DAMAGED", "WRONG_ITEM", "MISSING_ITEM", "NOT_AS_DESCRIBED", "CHANGE_OF_MIND"]) -> dict:
    """Deterministically check item-level return eligibility for an owned delivered order."""
    return (await check_return_eligibility_impl(trusted_context(), order_id, reason_code)).model_dump(mode="json")


@tool
async def get_active_incidents() -> dict:
    """Get active service incidents that may affect support answers."""
    return (await get_active_incidents_impl(trusted_context())).model_dump(mode="json")


@tool
async def search_knowledge(query: str, limit: int = 5) -> dict:
    """Search active eligible knowledge and return versioned evidence with public citations."""
    context = trusted_context()
    results = await retrieve(RetrievalRequest(query=query, locale=context.locale, visibility="CUSTOMER_AUTHENTICATED", limit=limit))
    return {"status": "SUCCESS", "data": {"results": [result.model_dump(mode="json") for result in results]}}


@tool
async def search_products(query: str = "", category: Optional[str] = None, max_price: Optional[float] = None, limit: int = 8) -> dict:
    """Search in-stock products by need, category, and optional maximum budget."""
    return (await search_products_impl(trusted_context(), query, category, max_price, limit)).model_dump(mode="json")


@tool
async def get_product_details(product_id: str) -> dict:
    """Read current product price, stock, rating, and metadata."""
    return (await get_product_details_impl(trusted_context(), product_id)).model_dump(mode="json")


@tool
async def get_customer_addresses() -> dict:
    """List verified delivery addresses owned by the authenticated customer."""
    return (await get_customer_addresses_impl(trusted_context())).model_dump(mode="json")


@tool
async def quote_checkout(checkout_id: str) -> dict:
    """Read a server-calculated checkout quote owned by the customer."""
    return (await quote_checkout_impl(trusted_context(), checkout_id)).model_dump(mode="json")


@tool
async def create_checkout_session(checkout_id: str, product_id: str, quantity: int) -> dict:
    """Create or update an owned checkout draft after explicit product and quantity selection."""
    return (await create_checkout_session_impl(trusted_context(), checkout_id, product_id, quantity)).model_dump(mode="json")


@tool
async def confirm_checkout(checkout_id: str) -> dict:
    """Create one real order from a confirmed checkout; idempotent and stock-safe."""
    return (await confirm_checkout_impl(trusted_context(), checkout_id)).model_dump(mode="json")


@tool
async def create_support_ticket(category: str, summary: str, priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"], order_id: Optional[str] = None) -> dict:
    """Create one idempotent support ticket after a handoff decision."""
    return (await create_support_ticket_impl(trusted_context(), category, summary, priority, order_id)).model_dump(mode="json")


@tool
async def cancel_order(order_id: str, reason: str) -> dict:
    """Cancel an owned order only when its current state permits cancellation."""
    return (await cancel_order_impl(trusted_context(), order_id, reason)).model_dump(mode="json")


@tool
async def create_return_request(order_id: str, reason_code: Literal["DAMAGED", "WRONG_ITEM", "MISSING_ITEM", "NOT_AS_DESCRIBED", "CHANGE_OF_MIND"]) -> dict:
    """Check policy and create an idempotent return request for eligible items in an owned delivered order."""
    return (await create_return_request_impl(trusted_context(), order_id, reason_code)).model_dump(mode="json")


@tool
async def create_shipping_investigation(order_id: str, issue: str) -> dict:
    """Create an idempotent shipping investigation for an owned shipped, out-for-delivery, or delivered order."""
    return (await create_shipping_investigation_impl(trusted_context(), order_id, issue)).model_dump(mode="json")


@tool
async def create_dispute(order_id: str, reason: str) -> dict:
    """Create an idempotent dispute for an owned delivered or cancelled order."""
    return (await create_dispute_impl(trusted_context(), order_id, reason)).model_dump(mode="json")


@tool
async def create_refund(order_id: str, reason: str) -> dict:
    """Create an idempotent demo refund for an owned delivered or cancelled order."""
    return (await create_refund_impl(trusted_context(), order_id, reason)).model_dump(mode="json")
