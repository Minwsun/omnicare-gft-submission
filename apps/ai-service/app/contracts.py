from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    FAILED = "FAILED"
    PENDING_APPROVAL = "PENDING_APPROVAL"


class ToolContext(BaseModel):
    request_id: str
    conversation_id: str
    customer_id: Optional[str] = None
    actor_role: Literal["CUSTOMER", "ADMIN", "REVIEWER"] = "CUSTOMER"
    channel: Literal["WEB", "EMAIL"] = "WEB"
    locale: str = "vi-VN"
    idempotency_key: Optional[str] = None


class ToolResult(BaseModel):
    status: ToolStatus
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    safe_message: Optional[str] = None
    source_system: str = "OMNICARE_DB"
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    freshness_seconds: int = 0
    reference_id: Optional[str] = None


class IncomingMessage(BaseModel):
    message_id: str
    content: str = Field(min_length=1, max_length=8000)
    customer_id: Optional[str] = None
    channel: Literal["WEB", "EMAIL"] = "WEB"
    conversation_id: str
    actor_role: Literal["CUSTOMER", "ADMIN", "REVIEWER"] = "CUSTOMER"
    locale: str = "vi-VN"
    page_context: Optional[Dict[str, Any]] = None


class Citation(BaseModel):
    document_id: str
    title: str
    section: str
    version: str
    effective_from: date
    public_url: Optional[str] = None
    snippet: Optional[str] = None
    score: Optional[float] = None


class CustomerContextUsed(BaseModel):
    type: Literal["CUSTOMER", "ORDER", "SHIPMENT", "PAYMENT", "REFUND"]
    reference_id: str
    observed_at: datetime


class AgentAction(BaseModel):
    type: str
    status: Literal["COMPLETED", "PENDING_APPROVAL", "FAILED"]
    reference_id: Optional[str] = None


class ToolExecutionSummary(BaseModel):
    name: str
    status: ToolStatus
    reference_id: Optional[str] = None


class AgentChoice(BaseModel):
    id: str
    label: str
    description: Optional[str] = None
    value: Dict[str, Any] = Field(default_factory=dict)


class AgentUiField(BaseModel):
    id: str
    type: Literal["TEXT", "TEXTAREA", "DATE", "DATETIME", "NUMBER", "FILE"]
    label: str
    required: bool = False
    placeholder: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None


class VerifiedDataBinding(BaseModel):
    type: Literal["CUSTOMER", "ORDER", "ORDER_ITEM", "PRODUCT", "CHECKOUT", "ADDRESS", "SHIPMENT", "PAYMENT", "REFUND", "TICKET"]
    reference_id: str


class VerifiedFact(BaseModel):
    key: str
    value: Any
    source: str
    reference_id: Optional[str] = None
    observed_at: Optional[datetime] = None


class ResponseQualityReport(BaseModel):
    coverage_score: float = Field(default=1, ge=0, le=1)
    propositions: List[str] = Field(default_factory=list)
    answered_propositions: List[str] = Field(default_factory=list)
    unanswered_propositions: List[str] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)
    missing_next_step: bool = False


class PendingAgentAction(BaseModel):
    action: str
    tool: str
    arguments: Dict[str, Any]
    confirmation_token: str
    expires_at: datetime


class AgentUiComponent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    type: Literal["CONFIRMATION", "SINGLE_CHOICE", "MULTI_CHOICE", "ORDER_SELECTOR", "PRODUCT_SELECTOR", "QUANTITY_SELECTOR", "ADDRESS_SELECTOR", "PAYMENT_METHOD_SELECTOR", "CHECKOUT_SUMMARY", "DATE_TIME_PICKER", "TEXT_INPUT", "TEXTAREA", "FILE_UPLOAD", "EVIDENCE_CHECKLIST", "SUMMARY_CARD", "ACTION_RESULT"]
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    confirm_label: Optional[str] = None
    cancel_label: Optional[str] = None
    prompt: Optional[str] = None
    options: List[AgentChoice] = Field(default_factory=list)
    fields: List[AgentUiField] = Field(default_factory=list)
    bindings: List[VerifiedDataBinding] = Field(default_factory=list)
    continuation_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    pending_action: Optional[PendingAgentAction] = None


class ClarificationRequest(BaseModel):
    reason: Literal["MISSING_ENTITY", "MISSING_REQUIRED_FIELD", "AMBIGUOUS_REFERENCE", "MULTIPLE_MATCHES", "POLICY_SCOPE_UNCLEAR", "ACTION_CONFIRMATION", "EVIDENCE_REQUIRED"]
    field: str
    question: str
    ui_type: Literal["SINGLE_CHOICE", "MULTI_CHOICE", "ORDER_SELECTOR", "PRODUCT_SELECTOR", "DATE_TIME_PICKER", "TEXT_INPUT", "TEXTAREA", "FILE_UPLOAD", "EVIDENCE_CHECKLIST", "CONFIRMATION"]
    suggested_options: List[str] = Field(default_factory=list)


class ResolutionOption(BaseModel):
    id: str
    title: str
    outcome: str
    eligibility: Literal["ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW"]
    advantages: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    required_evidence: List[str] = Field(default_factory=list)
    supporting_claims: List[str] = Field(default_factory=list)


class AdvisorRecommendation(BaseModel):
    option_id: str
    summary: str
    reason: str


class AdvisorEvidenceSummary(BaseModel):
    transaction_facts: List[str] = Field(default_factory=list)
    policy_claims: List[str] = Field(default_factory=list)


class OrderChoice(BaseModel):
    order_id: str
    status: str
    placed_at: datetime
    total_amount: float
    currency: str


class GroundedAgentResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    intent: Optional[str] = None
    conversation_mode: Literal["SOCIAL", "DOMAIN", "FOLLOW_UP", "OUT_OF_SCOPE"] = "DOMAIN"
    answer_style: Literal["FRIENDLY"] = "FRIENDLY"
    resolved_context: Dict[str, Any] = Field(default_factory=dict)
    complexity: Literal["SIMPLE", "MODERATE", "COMPLEX", "HIGH_RISK"] = "SIMPLE"
    diagnosis: Optional[str] = None
    goal: Optional[str] = None
    collected_slots: Dict[str, Any] = Field(default_factory=dict)
    missing_slots: List[str] = Field(default_factory=list)
    clarification: Optional[ClarificationRequest] = None
    resolution_status: Literal["NEEDS_INPUT", "READY_FOR_TOOLS", "READY_FOR_CONFIRMATION", "RESOLVED", "HANDOFF"] = "RESOLVED"
    next_best_action: Optional[str] = None
    recommendation: Optional[AdvisorRecommendation] = None
    alternatives: List[ResolutionOption] = Field(default_factory=list)
    missing_facts: List[str] = Field(default_factory=list)
    evidence_summary: AdvisorEvidenceSummary = Field(default_factory=AdvisorEvidenceSummary)
    case_state: Literal["OPEN", "AWAITING_INPUT", "AWAITING_CONFIRMATION", "HANDOFF", "RESOLVED"] = "OPEN"
    citations: List[Citation] = Field(default_factory=list)
    customer_context_used: List[CustomerContextUsed] = Field(default_factory=list)
    verified_facts: List[VerifiedFact] = Field(default_factory=list)
    quality: ResponseQualityReport = Field(default_factory=ResponseQualityReport)
    knowledge_gaps: List[str] = Field(default_factory=list)
    actions: List[AgentAction] = Field(default_factory=list)
    tool_calls: List[ToolExecutionSummary] = Field(default_factory=list)
    order_choices: List[OrderChoice] = Field(default_factory=list)
    ui: List[AgentUiComponent] = Field(default_factory=list)
    pending_action: Optional[PendingAgentAction] = None
    conversation_state: Literal["ANSWERED", "AWAITING_INPUT", "AWAITING_CONFIRMATION", "COMPLETED"] = "ANSWERED"
    requires_human: bool = False
    handoff_requested: bool = False
    handoff_confidence: float = Field(default=0, ge=0, le=1)
    escalation_reason: Optional[str] = None
    run_id: Optional[str] = None
    review_status: Literal["PASSED", "REWRITE", "FALLBACK", "HANDOFF"] = "PASSED"
    category: Optional[str] = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] = "LOW"
    priority_reasons: List[str] = Field(default_factory=list)
    request_fingerprint: Optional[str] = None
    duplicate_of: Optional[str] = None


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    locale: str = "vi-VN"
    visibility: Literal["PUBLIC", "CUSTOMER_AUTHENTICATED", "INTERNAL"] = "PUBLIC"
    limit: int = Field(default=5, ge=1, le=20)
    profile: Optional[str] = None


class QueryPlan(BaseModel):
    intent: Optional[str] = None
    concepts: List[str] = Field(default_factory=list)
    propositions: List[str] = Field(default_factory=list)
    required_evidence_types: List[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    document_id: str
    version_id: str
    chunk_id: str
    document_type: str
    title: str
    section: str
    content: str
    semantic_version: str
    score: float
    authority_level: int
    public_url: Optional[str]
    effective_from: datetime
    proposition_id: Optional[str] = None
    source_url: Optional[str] = None
    source_hash: Optional[str] = None
    graph_path: List[str] = Field(default_factory=list)
    entailment_score: Optional[float] = None
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    original_length: int = 0
    compressed_length: int = 0
    compression_reason: str = "QUERY_FOCUSED_EXTRACT"
    parent_summary: Optional[str] = None
    retrieval_channels: List[str] = Field(default_factory=list)


class ConfirmActionRequest(BaseModel):
    confirmation_token: str
    customer_id: str
    conversation_id: str


class AgentInteractionRequest(BaseModel):
    interaction_id: str
    conversation_id: str
    customer_id: str
    action: Literal["SELECT", "SUBMIT", "CONFIRM", "REJECT", "CANCEL"]
    values: Dict[str, Any] = Field(default_factory=dict)
    continuation_token: str


class GraphParseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=20, max_length=100000)
    kind: Literal["DOCUMENT", "FAQ", "POLICY", "TERMS", "RULE", "INTENT", "ACTION", "PRODUCT_SCOPE", "ORDER_STATUS", "PAYMENT_STATUS", "INCIDENT", "ESCALATION"]
    importance: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    visibility: Literal["PUBLIC", "CUSTOMER_AUTHENTICATED", "INTERNAL"] = "INTERNAL"
    marketplace: Literal["SHOPEE", "TIKTOK_SHOP", "INTERNAL"] = "INTERNAL"
    mandatory: bool = False
