from __future__ import annotations

import hashlib
import re
from typing import Optional

from pydantic import BaseModel, Field

from .policies import extract_order_ids, priority_score


class TriageResult(BaseModel):
    category: str
    priority: str
    priority_reasons: list[str] = Field(default_factory=list)
    request_fingerprint: str
    order_id: Optional[str] = None
    is_spam: bool = False
    requires_human: bool = False
    escalation_reason: Optional[str] = None


def normalize_request(content: str) -> str:
    text = content.casefold().strip()
    text = re.sub(r"https?://\S+", " url ", text)
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def detect_spam(content: str) -> bool:
    normalized = normalize_request(content)
    words = normalized.split()
    repeated = max((words.count(word) for word in set(words)), default=0)
    many_links = len(re.findall(r"https?://", content.casefold())) >= 3
    promotional = any(term in normalized for term in ("kiếm tiền nhanh", "quảng cáo miễn phí", "mua follow", "casino", "nhà cái"))
    return repeated >= 12 or many_links or promotional


def classify_category(content: str) -> str:
    text = normalize_request(content)
    if detect_spam(content):
        return "SPAM"
    if any(term in text for term in ("đe dọa", "nguy hiểm", "mất tài khoản", "người lạ vào tài khoản", "đăng nhập lạ", "giao dịch này không phải", "không nhận ra giao dịch", "lộ otp")):
        return "URGENT_SECURITY"
    if any(term in text for term in ("khiếu nại", "tranh chấp", "giao sai", "chưa nhận", "thái độ shipper", "hàng hỏng")):
        return "COMPLAINT"
    if any(term in text for term in ("thanh toán", "hoàn tiền", "trừ tiền", "refund")):
        return "PAYMENT"
    if any(term in text for term in ("app", "ứng dụng", "không đăng nhập", "bị văng", "lỗi kỹ thuật")):
        return "TECHNICAL"
    if any(term in text for term in ("giao hàng", "vận chuyển", "shipper", "đơn hàng", "ord-")):
        return "ORDER_SUPPORT"
    return "INFORMATION"


def triage_request(content: str, customer_id: Optional[str]) -> TriageResult:
    normalized = normalize_request(content)
    category = classify_category(content)
    order_ids = extract_order_ids(content)
    order_id = order_ids[0] if order_ids else None
    priority = priority_score(content)
    reasons: list[str] = []
    if priority["score"]:
        reasons.append("CONTENT_RISK")
    urgent = category == "URGENT_SECURITY" or priority["level"] == "URGENT"
    if urgent:
        reasons.append("URGENT_SAFETY_OR_SECURITY")
    if category == "COMPLAINT":
        reasons.append("CUSTOMER_COMPLAINT")
    identity = customer_id or "anonymous"
    digest = hashlib.sha256(f"{identity}|{category}|{order_id or ''}|{normalized}".encode("utf-8")).hexdigest()[:20].upper()
    return TriageResult(
        category=category,
        priority="URGENT" if urgent else str(priority["level"]),
        priority_reasons=reasons,
        request_fingerprint=digest,
        order_id=order_id,
        is_spam=category == "SPAM",
        requires_human=urgent,
        escalation_reason="URGENT_SAFETY_OR_SECURITY" if urgent else None,
    )
