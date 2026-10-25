from __future__ import annotations

from enum import Enum

from pydantic import Field

from ..models import Action, IssueType, ReviewStatus, SourceReference, StrictModel


class IssueClassification(str, Enum):
    OBJECTIVE = "OBJECTIVE"
    SEMANTIC_EXACT = "SEMANTIC_EXACT"
    AMBIGUOUS = "AMBIGUOUS"


class IssueOutcome(str, Enum):
    APPLIED = "APPLIED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    DEFERRED = "DEFERRED"
    SKIPPED_WITH_HUMAN_APPROVAL = "SKIPPED_WITH_HUMAN_APPROVAL"
    INVALID = "INVALID"


class PatchKind(str, Enum):
    REMOVE = "REMOVE"
    REPLACE = "REPLACE"


class PatchOperation(StrictModel):
    kind: PatchKind
    start: int
    end: int
    before: str
    after: str


class FixResult(StrictModel):
    classification: IssueClassification
    outcome: IssueOutcome
    content: str
    patches: list[PatchOperation] = Field(default_factory=list)
    reason: str


class ReconciledIssue(StrictModel):
    id: str
    agent_b_issue_index: int
    issue_type: IssueType
    explanation: str
    proposed_correction: str
    evidence_refs: list[SourceReference] = Field(default_factory=list)
    classification: IssueClassification
    outcome: IssueOutcome
    patches: list[PatchOperation] = Field(default_factory=list)
    human_decision_id: str | None = None


class ReconciledChangeStatus(str, Enum):
    READY = "READY"
    FIXED = "FIXED"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    INVALID = "INVALID"


class ValidationSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationFinding(StrictModel):
    code: str
    severity: ValidationSeverity
    message: str
    change_ids: list[str] = Field(default_factory=list)


class ReconciledChange(StrictModel):
    id: str
    agent_a_change_index: int
    original_action: Action
    original_target_path: str
    original_content_sha256: str
    agent_b_status: ReviewStatus
    agent_b_issue_indices: list[int] = Field(default_factory=list)
    issues: list[ReconciledIssue] = Field(default_factory=list)
    applied_fixes: list[PatchOperation] = Field(default_factory=list)
    human_decision_required: bool = False
    human_decision_ids: list[str] = Field(default_factory=list)
    final_action: Action | None = None
    final_target_path: str | None = None
    final_content: str | None = None
    final_content_sha256: str | None = None
    status: ReconciledChangeStatus
    validation_findings: list[ValidationFinding] = Field(default_factory=list)


class DecisionEffect(str, Enum):
    APPLY_RECONCILED_CHANGE = "APPLY_RECONCILED_CHANGE"
    REMOVE_LINK = "REMOVE_LINK"
    SKIP_CHANGE = "SKIP_CHANGE"
    DEFER = "DEFER"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class DecisionOption(StrictModel):
    key: str
    label: str
    effect: DecisionEffect


class HumanDecision(StrictModel):
    id: str
    change_ids: list[str]
    issue_ids: list[str]
    category: str
    status: DecisionStatus
    question: str
    context: str
    agent_a_position: str
    agent_b_position: str
    recommendation: str | None = None
    rationale: str | None = None
    confidence: str | None = None
    options: list[DecisionOption]
    selected_option: str | None = None


class PreReviewAdjustment(StrictModel):
    field: str
    before: object
    after: object


class FinalChangeSetState(str, Enum):
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    READY_FOR_WRITE = "READY_FOR_WRITE"
    INVALID = "INVALID"


class FinalChangeSet(StrictModel):
    source_run_id: str
    reconciliation_version: str
    provenance: dict[str, str]
    input_sha256: dict[str, str]
    pre_review_adjustments: list[PreReviewAdjustment]
    changes: list[ReconciledChange]
    human_decisions: list[HumanDecision]
    unresolved_decision_ids: list[str]
    validation_findings: list[ValidationFinding]
    state: FinalChangeSetState


class ReconciliationResult(StrictModel):
    final_change_set: FinalChangeSet
