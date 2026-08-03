import asyncio
import hashlib
import json
import re
import unicodedata
from typing import List

from .brand import omni_brand_text
from .async_cache import AsyncSingleFlightCache
from .contracts import QueryPlan, RetrievalRequest, RetrievalResult
from .config import settings
from .embeddings import embed_texts, vector_literal
from .repositories import Repository, repository


_retrieval_cache = AsyncSingleFlightCache[List[RetrievalResult]](
    settings.retrieval_cache_ttl_seconds,
    settings.retrieval_cache_max_entries,
)


STOPWORDS = {"là", "gì", "của", "tôi", "cho", "về", "cần", "muốn", "xin", "hãy", "được", "không", "cửa", "hàng", "như", "thế", "nào"}

PROFILE_TERMS = {
    "PAYMENT_POLICY": ("thanh toán", "cod", "thẻ", "ví", "payment"),
    "RETURN_POLICY": ("trả hàng", "đổi trả", "hoàn tiền", "return", "refund", "bằng chứng"),
    "REFUND_POLICY": ("hoàn tiền", "refund", "trả hàng"),
    "VOUCHER": ("voucher", "mã giảm giá", "khuyến mãi", "ưu đãi"),
    "ACCOUNT_SECURITY": ("tài khoản", "đăng nhập", "mật khẩu", "otp", "bảo mật", "email", "số điện thoại"),
    "PRIVACY": ("dữ liệu cá nhân", "dữ liệu", "thông tin cá nhân", "quyền riêng tư", "bảo mật", "privacy"),
    "FRAUD_WARNING": ("lừa đảo", "giả mạo", "chuyển khoản", "link", "otp", "an toàn"),
    "TECHNICAL_SUPPORT": ("ứng dụng", "app", "thông báo", "cập nhật", "bộ nhớ", "lỗi", "đăng xuất", "bị văng"),
    "SHIPPING_POLICY": ("vận chuyển", "giao hàng", "địa chỉ", "đơn vị vận chuyển", "shipping"),
}

TYPE_BOOSTS = {
    "PAYMENT_POLICY": {"POLICY": 0.12, "FAQ": 0.08, "GUIDE": 0.06},
    "RETURN_POLICY": {"POLICY": 0.16, "TERMS": 0.12, "FAQ": 0.06},
    "REFUND_POLICY": {"POLICY": 0.16, "TERMS": 0.12},
    "PRIVACY": {"POLICY": 0.18, "TERMS": 0.16},
    "ACCOUNT_SECURITY": {"GUIDE": 0.12, "TROUBLESHOOTING": 0.12, "FAQ": 0.08},
    "TECHNICAL_SUPPORT": {"TROUBLESHOOTING": 0.18, "GUIDE": 0.12, "FAQ": 0.08},
}

PROFILE_CONCEPTS = {
    "PAYMENT_POLICY": ("PAYMENT_METHOD", "PAYMENT_FAILURE"),
    "RETURN_POLICY": ("RETURN_ELIGIBILITY", "RETURN_REASON", "RETURN_EVIDENCE"),
    "REFUND_POLICY": ("REFUND_ELIGIBILITY", "REFUND_TIMELINE"),
    "VOUCHER": ("VOUCHER_ELIGIBILITY", "VOUCHER_COMBINATION"),
    "ACCOUNT_SECURITY": ("ACCOUNT_SECURITY", "IDENTITY_VERIFICATION"),
    "PRIVACY": ("PRIVACY_DATA_TYPE", "PRIVACY_PURPOSE", "PRIVACY_RIGHTS"),
    "FRAUD_WARNING": ("FRAUD_SIGNAL", "SAFE_RESPONSE"),
    "TECHNICAL_SUPPORT": ("APP_TROUBLESHOOTING", "APP_UPDATE", "CACHE_CLEAR", "NOTIFICATION_FAILURE"),
    "SHIPPING_POLICY": ("SHIPPING_TRACKING", "ADDRESS_CHANGE", "DELIVERY_SUPPORT"),
}

PROFILE_TITLE_TERMS = {
    "PAYMENT_POLICY": ("thanh toán", "cod", "thẻ", "ví"),
    "RETURN_POLICY": ("trả hàng", "đổi trả", "hoàn tiền", "bằng chứng"),
    "REFUND_POLICY": ("hoàn tiền", "trả hàng"),
    "VOUCHER": ("voucher", "mã giảm giá", "khuyến mãi"),
    "ACCOUNT_SECURITY": ("tài khoản", "đăng nhập", "mật khẩu", "bảo mật", "otp"),
    "PRIVACY": ("dữ liệu", "riêng tư", "bảo mật thông tin"),
    "FRAUD_WARNING": ("lừa đảo", "giả mạo", "an toàn"),
    "TECHNICAL_SUPPORT": ("ứng dụng", "app", "thông báo", "cập nhật", "lỗi"),
    "SHIPPING_POLICY": ("giao hàng", "vận chuyển", "địa chỉ"),
}

CONCEPT_QUERIES = {
    "PAYMENT_METHOD": "phương thức thanh toán",
    "PAYMENT_FAILURE": "không thể thanh toán lỗi thanh toán",
    "RETURN_ELIGIBILITY": "điều kiện trả hàng hoàn tiền",
    "RETURN_REASON": "lý do trả hàng sai thiếu lỗi sản phẩm",
    "RETURN_EVIDENCE": "bằng chứng trả hàng hoàn tiền",
    "REFUND_ELIGIBILITY": "điều kiện hoàn tiền",
    "REFUND_TIMELINE": "thời gian nhận tiền hoàn",
    "VOUCHER_ELIGIBILITY": "điều kiện sử dụng voucher mã giảm giá",
    "VOUCHER_COMBINATION": "kết hợp nhiều voucher mã giảm giá",
    "ACCOUNT_SECURITY": "bảo mật tài khoản đăng nhập",
    "IDENTITY_VERIFICATION": "xác minh tài khoản OTP",
    "PRIVACY_DATA_TYPE": "loại dữ liệu cá nhân thu thập lưu trữ",
    "PRIVACY_PURPOSE": "mục đích sử dụng thông tin cá nhân",
    "PRIVACY_RIGHTS": "quyền dữ liệu cá nhân",
    "FRAUD_SIGNAL": "dấu hiệu lừa đảo giả mạo",
    "SAFE_RESPONSE": "cách bảo vệ tài khoản giao dịch an toàn",
    "APP_TROUBLESHOOTING": "lỗi khi sử dụng ứng dụng",
    "APP_UPDATE": "cập nhật ứng dụng phiên bản mới nhất",
    "CACHE_CLEAR": "xóa bộ nhớ đệm cache ứng dụng",
    "NOTIFICATION_FAILURE": "không nhận được thông báo ứng dụng",
    "SHIPPING_TRACKING": "theo dõi hành trình đơn hàng vận chuyển",
    "ADDRESS_CHANGE": "thay đổi địa chỉ nhận hàng đơn đã đặt",
    "DELIVERY_SUPPORT": "liên hệ hỗ trợ đơn vị vận chuyển giao chậm",
}


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(character for character in decomposed if unicodedata.category(character) != "Mn").replace("đ", "d")


def lexical_score(query_terms: list[str], profile_terms: tuple[str, ...], row) -> float:
    title = normalize_text(f"{row['title']} {row['section']}")
    content = normalize_text(row["content"])
    text = f"{title} {content}"
    title_hits = sum(normalize_text(term) in title for term in query_terms)
    content_hits = sum(normalize_text(term) in content for term in query_terms)
    profile_hits = sum(normalize_text(term) in text for term in profile_terms)
    exact_title = normalize_text(" ".join(query_terms)) in title if query_terms else False
    return min(0.55, title_hits * 0.09 + content_hits * 0.018 + profile_hits * 0.018 + (0.14 if exact_title else 0))


def profile_matches(profile_terms: tuple[str, ...], row) -> bool:
    if not profile_terms:
        return True
    text = normalize_text(f"{row['title']} {row['section']} {row['content']}")
    return any(normalize_text(term) in text for term in profile_terms)


def compress_content(query: str, content: str, document_type: str, profile_terms: tuple[str, ...]) -> tuple[str, str]:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", content) if item.strip()]
    if len(sentences) <= 2:
        return content.strip(), "FULL_SHORT_SOURCE"
    query_terms = {normalize_text(term) for term in re.findall(r"[\wÀ-ỹ]+", query, flags=re.UNICODE) if len(term) >= 3 and term.casefold() not in STOPWORDS}
    query_terms.update(normalize_text(term) for term in profile_terms)
    protected = re.compile(r"\b(?:không|chỉ|phải|được|trừ|ngoại lệ|trong vòng|ngày|giờ|phút|vnd|%|điều kiện|thời hạn)\b|\d", re.IGNORECASE)
    ranked = []
    for index, sentence in enumerate(sentences):
        normalized = normalize_text(sentence)
        matches = sum(term in normalized for term in query_terms)
        preserve = document_type in {"POLICY", "TERMS"} and bool(protected.search(sentence))
        score = matches * 3 + (2 if preserve else 0) + (1 if index == 0 else 0)
        if score > 0:
            ranked.append((score, index, sentence))
    if not ranked:
        return " ".join(sentences[:2]), "LEAD_FALLBACK"
    selected_indexes = {index for _, index, _ in sorted(ranked, key=lambda item: (-item[0], item[1]))[:8]}
    if document_type in {"POLICY", "TERMS"}:
        for _, index, _ in ranked:
            if index in selected_indexes:
                if index > 0 and protected.search(sentences[index - 1]): selected_indexes.add(index - 1)
                if index + 1 < len(sentences) and protected.search(sentences[index + 1]): selected_indexes.add(index + 1)
    compressed = " ".join(sentences[index] for index in sorted(selected_indexes))
    return compressed, "POLICY_SAFE_EXTRACT" if document_type in {"POLICY", "TERMS"} else "QUERY_FOCUSED_EXTRACT"


def decompose_query(query: str) -> list[str]:
    parts = [part.strip(" ,.;?!") for part in re.split(r"\b(?:và|rồi|đồng thời|còn)\b|[?;]", query, flags=re.IGNORECASE)]
    meaningful = [part for part in parts if len(part) >= 6]
    return list(dict.fromkeys(meaningful))[:2] or [query]


def build_query_plan(request: RetrievalRequest) -> QueryPlan:
    concepts = list(PROFILE_CONCEPTS.get(request.profile or "", ()))
    evidence_types = ["POLICY_CLAIM"] if request.profile and (request.profile.endswith("POLICY") or request.profile in {"PRIVACY", "VOUCHER"}) else ["SUPPORT_GUIDE"]
    return QueryPlan(intent=request.profile, concepts=concepts, propositions=decompose_query(request.query), required_evidence_types=evidence_types)


def build_search_queries(request: RetrievalRequest, plan: QueryPlan, focused: list[str], profile_terms: tuple[str, ...]) -> list[str]:
    proposition_queries = [" ".join(word for word in re.findall(r"[\wÀ-ỹ]+", item.lower(), flags=re.UNICODE) if word not in STOPWORDS) for item in plan.propositions]
    concept_queries = [CONCEPT_QUERIES[concept] for concept in plan.concepts if concept in CONCEPT_QUERIES]
    expansions = [term for term in profile_terms if normalize_text(term) not in normalize_text(request.query)][:1]
    discriminative_terms = sorted(set(focused), key=lambda term: (-len(term), term))[:2]
    return list(dict.fromkeys([*proposition_queries, *concept_queries, *expansions, *discriminative_terms]))[:3] or [request.query]


def _retrieval_cache_key(request: RetrievalRequest, store: Repository) -> str:
    payload = {
        **request.model_dump(mode="json"),
        "generation": _retrieval_cache.generation,
        "store": "repository" if store is repository else f"custom:{id(store)}",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


async def clear_retrieval_cache() -> None:
    await _retrieval_cache.clear()


async def retrieve(request: RetrievalRequest, store: Repository = repository) -> List[RetrievalResult]:
    key = _retrieval_cache_key(request, store)
    results, cache_hit = await _retrieval_cache.get_or_compute(key, lambda: _retrieve_uncached(request, store))
    copies = [item.model_copy(deep=True) for item in results]
    for item in copies:
        item.score_breakdown["cache_hit"] = cache_hit
    return copies


async def _retrieve_uncached(request: RetrievalRequest, store: Repository = repository) -> List[RetrievalResult]:
    words = [word for word in re.findall(r"[\wÀ-ỹ]+", request.query.lower(), flags=re.UNICODE) if word not in STOPWORDS]
    focused = [word for word in words if len(word) >= 3]
    profile_terms = PROFILE_TERMS.get(request.profile or "", ())
    normalized_query = normalize_text(request.query)
    query_profile_terms = tuple(term for term in profile_terms if normalize_text(term) in normalized_query)
    plan = build_query_plan(request)
    propositions = plan.propositions
    concept_queries = [CONCEPT_QUERIES[concept] for concept in plan.concepts if concept in CONCEPT_QUERIES]
    ranking_terms = list(dict.fromkeys([*focused, *(word for query in concept_queries for word in re.findall(r"[\wÀ-ỹ]+", query.lower(), flags=re.UNICODE))]))
    queries = build_search_queries(request, plan, focused, profile_terms)
    text_batches = await asyncio.gather(*(store.search_knowledge(query, request.locale, request.limit * 2, request.visibility) for query in queries))
    lexical_rows = [row for rows in text_batches for row in rows]
    lexical_is_strong = (
        len({row["chunk_id"] for row in lexical_rows}) >= min(request.limit, settings.retrieval_max_chunks)
        and max((float(row.get("score") or 0) for row in lexical_rows), default=0) >= settings.lexical_fast_path_score
    )
    vector_batch = []
    if not lexical_is_strong and hasattr(store, "search_knowledge_vector"):
        try:
            vectors = await embed_texts([request.query])
            if vectors:
                vector_batch = await store.search_knowledge_vector(vector_literal(vectors[0]), request.locale, request.limit * 3, request.visibility)
        except Exception:
            vector_batch = []
    merged: dict[str, dict] = {}
    for channel, weight, batches in (("FULL_TEXT", 1.0, text_batches),):
        for rows in batches:
            for rank, row in enumerate(rows, 1):
                chunk_id = row["chunk_id"]
                current = merged.setdefault(chunk_id, {**row, "score": 0.0, "retrieval_channels": [], "raw_retrieval": 0.0})
                current["score"] += weight * (60 / (60 + rank)) * 0.35
                current["raw_retrieval"] = max(float(current["raw_retrieval"]), float(row["score"]))
                if channel not in current["retrieval_channels"]:
                    current["retrieval_channels"].append(channel)
    for rank, row in enumerate(vector_batch, 1):
        chunk_id = row["chunk_id"]
        current = merged.setdefault(chunk_id, {**row, "score": 0.0, "retrieval_channels": [], "raw_retrieval": 0.0})
        current["score"] += 0.95 * (60 / (60 + rank)) * 0.35
        current["raw_retrieval"] = max(float(current["raw_retrieval"]), float(row["score"]))
        if "VECTOR" not in current["retrieval_channels"]:
            current["retrieval_channels"].append("VECTOR")
    results = []
    title_counts: dict[str, int] = {}
    for row in merged.values():
        if not profile_matches(profile_terms, row):
            continue
        if len(query_profile_terms) >= 2:
            candidate_text = normalize_text(f"{row['title']} {row['section']} {row['content']}")
            if sum(normalize_text(term) in candidate_text for term in query_profile_terms) < 2:
                continue
        if title_counts.get(row["title"], 0) >= 2:
            continue
        title_counts[row["title"]] = title_counts.get(row["title"], 0) + 1
        lexical = lexical_score(ranking_terms, profile_terms, row)
        type_boost = TYPE_BOOSTS.get(request.profile or "", {}).get(row["document_type"], 0)
        authority_boost = min(0.12, row["authority_level"] * 0.0012)
        retrieval_score = min(0.65, float(row["score"]))
        score = min(1.0, retrieval_score + authority_boost + lexical + type_boost)
        row = {**row, "title": omni_brand_text(row["title"]), "section": omni_brand_text(row["section"]), "content": omni_brand_text(row["content"]), "parent_summary": omni_brand_text(row.get("parent_summary") or "") or None}
        original_content = row["content"]
        compressed_content, compression_reason = compress_content(request.query, original_content, row["document_type"], profile_terms)
        compression_ratio = len(compressed_content) / max(1, len(original_content))
        results.append(RetrievalResult(**{**row, "content": compressed_content, "score": score, "score_breakdown": {"rrf": retrieval_score, "raw_retrieval": float(row.get("raw_retrieval") or 0), "lexical": lexical, "type": type_boost, "authority": authority_boost, "compression_ratio": compression_ratio, "final": score}, "original_length": len(original_content), "compressed_length": len(compressed_content), "compression_reason": compression_reason}))
    results.sort(key=lambda item: item.score, reverse=True)
    title_terms = PROFILE_TITLE_TERMS.get(request.profile or "", ())
    if title_terms:
        topical = [item for item in results if any(normalize_text(term) in normalize_text(f"{item.title} {item.section}") for term in title_terms)]
        if topical:
            results = topical
    selected = []
    context_tokens = 0
    for item in results:
        estimated_tokens = max(1, item.compressed_length // 4)
        if selected and context_tokens + estimated_tokens > settings.retrieval_token_budget:
            continue
        item.score_breakdown["context_token_estimate"] = estimated_tokens
        item.score_breakdown["context_token_budget"] = settings.retrieval_token_budget
        selected.append(item)
        context_tokens += estimated_tokens
        if len(selected) >= min(request.limit, settings.retrieval_max_chunks):
            break
    for item in selected:
        item.score_breakdown["selected_context_tokens"] = context_tokens
    return selected
