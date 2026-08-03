from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import IncomingMessage, ToolContext


@dataclass(frozen=True)
class TrustedContext:
    request_id: str
    conversation_id: str
    customer_id: str | None
    actor_role: str
    channel: str
    locale: str
    page_context: dict[str, Any]
    idempotency_key: str

    @classmethod
    def from_message(cls, message: IncomingMessage) -> "TrustedContext":
        return cls(
            request_id=message.message_id,
            conversation_id=message.conversation_id,
            customer_id=message.customer_id,
            actor_role=message.actor_role,
            channel=message.channel,
            locale=message.locale,
            page_context=message.page_context or {},
            idempotency_key=f"{message.conversation_id}:{message.message_id}",
        )

    def tool_context(self) -> ToolContext:
        return ToolContext(
            request_id=self.request_id,
            conversation_id=self.conversation_id,
            customer_id=self.customer_id,
            actor_role=self.actor_role,
            channel=self.channel,
            locale=self.locale,
            idempotency_key=self.idempotency_key,
        )
