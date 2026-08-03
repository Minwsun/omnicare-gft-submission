from __future__ import annotations

from typing import Any, TypedDict


class AgentHarnessState(TypedDict, total=False):
    message: dict[str, Any]
    normalized_query: str
    canonical_query: str
    semantic_intent: str
    semantic_confidence: float
    semantic_entities: dict[str, Any]
    semantic_ambiguities: list[str]
    understanding_fallback: bool
    order_id: str | None
    active_context: dict[str, Any]
    memory_digest: str
    risk_flags: list[str]
    blocked: bool
    heuristic_intent: str
    route: dict[str, Any]
    plan: dict[str, Any]
    adaptive_plan: dict[str, Any]
    selected_skills: list[dict[str, Any]]
    tool_policy: dict[str, dict[str, Any]]
