import httpx
import time
from collections import OrderedDict

from .config import settings


_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
_client: httpx.AsyncClient | None = None


def _http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30)
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts or not settings.embedding_model or not settings.llm_api_key:
        return []
    now = time.monotonic()
    results: list[list[float] | None] = []
    missing: list[str] = []
    for text in texts:
        cached = _cache.get(text)
        if cached and now - cached[0] < settings.embedding_cache_ttl_seconds:
            _cache.move_to_end(text)
            results.append(cached[1])
        else:
            results.append(None)
            missing.append(text)
    if not missing:
        return [vector for vector in results if vector is not None]
    base_url = (settings.llm_base_url or "").rstrip("/")
    response = await _http_client().post(
        f"{base_url}/embeddings",
        headers={"authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": settings.embedding_model, "input": missing},
    )
    response.raise_for_status()
    vectors = [item["embedding"] for item in sorted(response.json().get("data", []), key=lambda item: item.get("index", 0))]
    if len(vectors) != len(missing) or any(len(vector) != settings.embedding_dimensions for vector in vectors):
        raise RuntimeError("INVALID_EMBEDDING_DIMENSIONS")
    for text, vector in zip(missing, vectors):
        _cache[text] = (now, vector)
        _cache.move_to_end(text)
    while len(_cache) > settings.embedding_cache_max_entries:
        _cache.popitem(last=False)
    iterator = iter(vectors)
    return [vector if vector is not None else next(iterator) for vector in results]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
