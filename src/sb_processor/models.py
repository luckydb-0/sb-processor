from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .extraction import ProcessingCompleteness


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScannedNote(StrictModel):
    path: str
    filename: str
    title: str
    note_type: str | None
    aliases: list[str]
    maps: list[str]
    frontmatter: dict[str, Any]
    body: str
    mtime: float
    content_hash: str


class CandidateMatch(StrictModel):
    path: str
    title: str
    note_type: str | None
    match_kind: str
    score: float
    filename: str = ""
    aliases: list[str] = Field(default_factory=list)
    maps: list[str] = Field(default_factory=list)
    retrieval_methods: list[str] = Field(default_factory=list)
    lexical_score: float | None = None
    semantic_score: float | None = None


class NoteMetadata(StrictModel):
    path: str
    filename: str
    title: str
    note_type: str | None
    aliases: list[str]
    maps: list[str]
    content_hash: str = ""


class Action(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    NO_CHANGE = "NO_CHANGE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CandidateImportance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CandidateConcept(StrictModel):
    proposed_name: str
    aliases_or_terms_seen: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    reason: str
    importance: CandidateImportance = CandidateImportance.MEDIUM


class CandidateMap(StrictModel):
    proposed_name: str
    source_pages: list[int] = Field(default_factory=list)
    reason: str


class CandidateSourceNote(StrictModel):
    note_type: str
    proposed_name: str
    source_pages: list[int] = Field(default_factory=list)
    reason: str


class SourceAnalysis(StrictModel):
    source_identity: str
    candidate_concepts: list[CandidateConcept]
    candidate_maps: list[CandidateMap]
    source_level_observations: list[str]
    source_note_candidates: list[CandidateSourceNote] = Field(default_factory=list)


class ConceptRelation(str, Enum):
    NEW_CONCEPT = "NEW_CONCEPT"
    EQUIVALENT_EXISTING = "EQUIVALENT_EXISTING"
    BROADER_THAN_EXISTING = "BROADER_THAN_EXISTING"
    NARROWER_THAN_EXISTING = "NARROWER_THAN_EXISTING"
    RELATED_BUT_DISTINCT = "RELATED_BUT_DISTINCT"
    AMBIGUOUS = "AMBIGUOUS"


class ConceptResolution(StrictModel):
    candidate_name: str
    relation: ConceptRelation
    existing_path: str | None = None
    reason: str


class DraftChange(StrictModel):
    action: Action
    note_type: str
    title: str
    target_path: str
    reason: str
    content: str
    sources: list[str]


class LLMProposal(StrictModel):
    source_summary: str
    note_changes: list[DraftChange]
    review_required: list[str]
    concept_resolutions: list[ConceptResolution] = Field(default_factory=list)


class NoteChange(DraftChange):
    candidate_existing_notes: list[CandidateMatch]
    original_content_hash: str | None


class ProcessingProposal(StrictModel):
    workflow: str
    source: str
    source_summary: str
    vault_note_count: int
    note_changes: list[NoteChange]
    review_required: list[str]
    source_completeness: ProcessingCompleteness | None = None
    concept_resolutions: list[ConceptResolution] = Field(default_factory=list)


class ReviewStatus(str, Enum):
    PASS = "PASS"
    FIX = "FIX"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ReviewCategory(str, Enum):
    SOURCE_FIDELITY = "source_fidelity"
    CLAIM_STRENGTH = "claim_strength"
    SOURCE_INDEPENDENCE = "source_independence"
    SOURCE_SPECIFIC_RESULTS = "source_specific_results"
    PROVENANCE = "provenance"
    METADATA = "metadata"
    DUPLICATE_CONCEPT = "duplicate_concept"
    EXISTING_NOTE_INTEGRITY = "existing_note_integrity"
    DOT_PROMOTION = "dot_promotion"
    CONCEPT_BOUNDARIES = "concept_boundaries"
    ALIASES = "aliases"
    LINKS = "links"
    MAP_STRUCTURE = "map_structure"
    COURSE_STRUCTURE = "course_structure"
    LECTURE_STRUCTURE = "lecture_structure"
    SYNTHESIS = "synthesis"
    WORKFLOW_CONTAMINATION = "workflow_contamination"
    NAMING = "naming"
    CUMULATIVE_INTEGRITY = "cumulative_integrity"


class SourceReference(StrictModel):
    page: int | None = None
    note_path: str | None = None
    reference: str


class ReviewCheck(StrictModel):
    category: ReviewCategory
    status: CheckStatus
    explanation: str | None = None
    evidence_refs: list[SourceReference] = Field(default_factory=list)


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IssueType(str, Enum):
    SOURCE_FIDELITY = "source_fidelity"
    CLAIM_STRENGTH = "claim_strength"
    SOURCE_INDEPENDENT_WORDING = "source_independent_wording"
    SOURCE_SPECIFIC_RESULT = "source_specific_result"
    PROVENANCE = "provenance"
    METADATA = "metadata"
    DUPLICATE_CONCEPT = "duplicate_concept"
    EXISTING_NOTE = "existing_note"
    DOT_PROMOTION = "dot_promotion"
    CONCEPT_BOUNDARY = "concept_boundary"
    ALIAS = "alias"
    LINK = "link"
    MAP = "map"
    COURSE = "course"
    LECTURE = "lecture"
    VERBOSITY = "verbosity"
    WORKFLOW_CONTAMINATION = "workflow_contamination"
    TEMPLATE = "template"
    NAMING = "naming"
    CUMULATIVE_INTEGRITY = "cumulative_integrity"
    EVIDENCE_GAP = "evidence_gap"


class ReviewIssue(StrictModel):
    change_path: str
    issue_type: IssueType
    severity: IssueSeverity
    explanation: str
    proposed_correction: str
    source_pages: list[int] = Field(default_factory=list)
    evidence_refs: list[SourceReference] = Field(default_factory=list)
    corrected_content: str | None = None


class ReviewedChange(StrictModel):
    change_path: str
    status: ReviewStatus
    checks: list[ReviewCheck]
    issue_indices: list[int] = Field(default_factory=list)


class GlobalReviewIssue(StrictModel):
    category: ReviewCategory
    status: ReviewStatus
    affected_paths: list[str]
    explanation: str
    recommendation: str
    supporting_issue_indices: list[int] = Field(default_factory=list)


class GlobalBatchReview(StrictModel):
    issues: list[GlobalReviewIssue]
    summary: str


class ReviewResult(StrictModel):
    overall_status: ReviewStatus
    issues: list[ReviewIssue]
    reviewed_changes: list[ReviewedChange]
    global_review: GlobalBatchReview | None = None


class AliasRelation(str, Enum):
    IDENTITY_EQUIVALENT = "IDENTITY_EQUIVALENT"
    SUBTYPE = "SUBTYPE"
    VARIANT = "VARIANT"
    IMPLEMENTATION = "IMPLEMENTATION"
    PARENT_CHILD = "PARENT_CHILD"
    RELATED = "RELATED"
    SOURCE_WORDING = "SOURCE_WORDING"
    AMBIGUOUS = "AMBIGUOUS"


class AliasAssessment(StrictModel):
    alias: str
    relation: AliasRelation
    status: ReviewStatus
    explanation: str
    proposed_correction: str
    evidence_refs: list[SourceReference] = Field(default_factory=list)


class PromotionAssessment(StrictModel):
    status: ReviewStatus
    explanation: str
    proposed_correction: str
    substantive_content: bool | None = None
    foundational_identity: bool | None = None
    evidence_refs: list[SourceReference] = Field(default_factory=list)


class ChangeReview(StrictModel):
    status: ReviewStatus
    issues: list[ReviewIssue]
    checks: list[ReviewCheck]
    alias_assessments: list[AliasAssessment] = Field(default_factory=list)
    promotion_assessment: PromotionAssessment | None = None
