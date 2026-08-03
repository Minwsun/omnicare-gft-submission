from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..contracts import Citation, ToolResult


class PropositionPlan(BaseModel):
    id: str
    text: str
    intent: str
    order_id: str | None = None
    required_tools: list[str] = Field(default_factory=list)
    retrieval_profile: str | None = None
    risk: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"


class ExecutionBatch(BaseModel):
    id: str
    mode: Literal["PARALLEL", "SEQUENTIAL"] = "PARALLEL"
    proposition_ids: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    proposition_id: str
    source: str
    status: str
    facts: dict[str, Any] = Field(default_factory=dict)
    reference_id: str | None = None
    freshness_seconds: int = 0


class EvidencePackage(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AgentDecision(BaseModel):
    type: Literal["ANSWER", "CLARIFY", "CONFIRM", "PENDING_APPROVAL", "HANDOFF", "REFUSE"]
    reason: str
    proposition_ids: list[str] = Field(default_factory=list)


class ReviewVerdict(BaseModel):
    status: Literal["PASSED", "REWRITE", "FALLBACK", "HANDOFF"]
    errors: list[str] = Field(default_factory=list)
    coverage: float = Field(default=1, ge=0, le=1)


class ToolExecutionRecord(BaseModel):
    name: str
    result: ToolResult
    latency_ms: int
    attempts: int
    policy_reason: str


class ExecutionBudget(BaseModel):
    max_specialists: int = Field(default=3, ge=1, le=6)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
    max_wall_time_seconds: float = Field(default=15, gt=0, le=60)


class AgentTask(BaseModel):
    id: str
    capability: str
    objective: str
    specialist: str
    required_tools: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class AgentPlan(BaseModel):
    goal: str
    tasks: list[AgentTask] = Field(default_factory=list)
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    completion_criteria: list[str] = Field(default_factory=list)


class EvidenceClaim(BaseModel):
    claim: str
    source: str
    reference_id: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    verified: bool = True


class EvidenceBlackboard(BaseModel):
    claims: list[EvidenceClaim] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
