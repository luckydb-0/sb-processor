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


class IssueResolutionDisposition(str, Enum):
    ISSUE_FIXED = "ISSUE_FIXED"
    ISSUE_EXPLICITLY_ACCEPTED = "ISSUE_EXPLICITLY_ACCEPTED"
    ISSUE_UNRESOLVED = "ISSUE_UNRESOLVED"


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
    resolution: IssueResolutionDisposition = IssueResolutionDisposition.ISSUE_UNRESOLVED


class ReconciledChangeStatus(str, Enum):
    READY = "READY"
    FIXED = "FIXED"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    SKIPPED = "SKIPPED"
    INVALID = "INVALID"


class ValidationSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationFinding(StrictModel):
    code: str
    severity: ValidationSeverity
    message: str
    change_ids: list[str] = Field(default_factory=list)


class DependencyTargetState(str, Enum):
    TARGET_EXISTS_IN_VAULT = "TARGET_EXISTS_IN_VAULT"
    TARGET_CREATED_IN_BATCH = "TARGET_CREATED_IN_BATCH"
    TARGET_UPDATED_IN_BATCH = "TARGET_UPDATED_IN_BATCH"
    TARGET_DEFERRED = "TARGET_DEFERRED"
    TARGET_SKIPPED = "TARGET_SKIPPED"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"


class DependencyRecord(StrictModel):
    id: str
    source_change_id: str
    source_path: str
    token: str
    normalized_target: str
    target_state: DependencyTargetState
    target_path: str | None = None
    target_change_id: str | None = None
    blocking: bool
    root_decision_id: str | None = None


class IdentityClaimKind(str, Enum):
    CANONICAL_PATH = "CANONICAL_PATH"
    BASENAME = "BASENAME"
    TITLE = "TITLE"
    ALIAS = "ALIAS"


class IdentityClaim(StrictModel):
    value: str
    normalized: str
    kind: IdentityClaimKind
    canonical_path: str
    change_id: str | None = None
    from_existing_vault: bool


class IdentityCollision(StrictModel):
    id: str
    normalized_identity: str
    claims: list[IdentityClaim]
    change_ids: list[str] = Field(default_factory=list)
    dependent_change_ids: list[str] = Field(default_factory=list)
    blocking: bool
    human_decision_id: str | None = None


class MaterialLossKind(str, Enum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"


class MaterialLossRecord(StrictModel):
    id: str
    change_id: str
    kind: MaterialLossKind
    excerpt: str
    source_content_sha256: str
    disposition: IssueResolutionDisposition = IssueResolutionDisposition.ISSUE_UNRESOLVED
    decision_id: str | None = None


class ReconciledChange(StrictModel):
    id: str
    agent_a_change_index: int
    original_action: Action
    original_target_path: str
    original_content_sha256: str
    expected_existing_content_sha256: str | None = None
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
    dependencies: list[DependencyRecord] = Field(default_factory=list)
    material_losses: list[MaterialLossRecord] = Field(default_factory=list)


class DecisionEffect(str, Enum):
    APPLY_RECONCILED_CHANGE = "APPLY_RECONCILED_CHANGE"
    REMOVE_LINK = "REMOVE_LINK"
    SKIP_CHANGE = "SKIP_CHANGE"
    DEFER = "DEFER"
    KEEP_SEPARATE = "KEEP_SEPARATE"
    ACKNOWLEDGE_CONTENT_LOSS = "ACKNOWLEDGE_CONTENT_LOSS"
    ACCEPT_STAGED_RISK = "ACCEPT_STAGED_RISK"


class DecisionCategory(str, Enum):
    CONCEPT_IDENTITY = "CONCEPT_IDENTITY"
    MERGE_OR_SEPARATE = "MERGE_OR_SEPARATE"
    CONTENT_PRESERVATION = "CONTENT_PRESERVATION"
    STRUCTURAL_CHANGE = "STRUCTURAL_CHANGE"
    UNRESOLVED_DEPENDENCY = "UNRESOLVED_DEPENDENCY"
    SEMANTIC_RISK = "SEMANTIC_RISK"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class DecisionOption(StrictModel):
    key: str
    label: str
    effect: DecisionEffect
    consequence: str = ""


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
    blocking: bool = True


class AcceptedRisk(StrictModel):
    id: str
    category: DecisionCategory
    change_ids: list[str]
    issue_ids: list[str] = Field(default_factory=list)
    material_loss_ids: list[str] = Field(default_factory=list)
    decision_id: str
    selected_option: str
    description: str
    evidence: list[str] = Field(default_factory=list)


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
    dependencies: list[DependencyRecord] = Field(default_factory=list)
    identity_collisions: list[IdentityCollision] = Field(default_factory=list)
    accepted_risks: list[AcceptedRisk] = Field(default_factory=list)
    applicable_change_ids: list[str] = Field(default_factory=list)


class ReconciliationResult(StrictModel):
    final_change_set: FinalChangeSet
