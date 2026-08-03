import re
from typing import Dict, List


ORDER_PATTERN = re.compile(r"\bORD-\d{4,}\b", re.IGNORECASE)
HIGH_RISK_TERMS = ("lừa đảo", "xóa tài khoản", "đe dọa", "an toàn", "fraud")
HUMAN_TERMS = ("nhân viên", "người thật", "gặp người", "khiếu nại")


def extract_order_ids(content: str) -> List[str]:
    return list(dict.fromkeys(match.upper() for match in ORDER_PATTERN.findall(content)))


def classify_intent(content: str) -> str:
    text = content.lower()
    if any(term in text for term in HUMAN_TERMS):
        return "HUMAN_REQUEST"
    if not ORDER_PATTERN.search(content) and any(term in text for term in ("chính sách", "điều kiện", "quy định", "hướng dẫn", "bao lâu", "thời hạn")):
        return "GENERAL_SUPPORT"
    if any(term in text for term in ("hoàn tiền", "refund")):
        return "REFUND"
    if any(term in text for term in ("thanh toán", "payment", "trừ tiền")):
        return "PAYMENT_STATUS"
    if any(term in text for term in ("giao", "ship", "vận chuyển", "đơn hàng", "đơn ord-")):
        return "ORDER_SHIPPING"
    return "GENERAL_SUPPORT"


def risk_flags(content: str) -> List[str]:
    text = content.lower()
    flags = []
    if any(term in text for term in HIGH_RISK_TERMS):
        flags.append("HIGH_RISK_CONTENT")
    if "bỏ qua hướng dẫn" in text or "system prompt" in text or "ignore previous" in text:
        flags.append("PROMPT_INJECTION")
    return flags


def priority_score(content: str, contact_count: int = 1, order_amount: int = 0) -> Dict[str, object]:
    text = content.lower()
    score = 0
    if "fraud" in text or "lừa đảo" in text:
        score += 50
    if any(term in text for term in ("tức giận", "quá tệ", "bực")):
        score += 15
    if contact_count >= 3:
        score += 15
    if order_amount >= 5_000_000:
        score += 10
    if any(term in text for term in ("an toàn", "đe dọa")):
        score += 100
    if any(term in text for term in ("đã giao nhưng chưa nhận", "delivered not received")):
        score += 40
    level = "LOW" if score < 20 else "MEDIUM" if score < 40 else "HIGH" if score < 70 else "URGENT"
    return {"score": score, "level": level}
