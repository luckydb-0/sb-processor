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


class CandidateConcept(StrictModel):
    proposed_name: str
    aliases_or_terms_seen: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    reason: str


class CandidateMap(StrictModel):
    proposed_name: str
    source_pages: list[int] = Field(default_factory=list)
    reason: str


class SourceAnalysis(StrictModel):
    source_identity: str
    candidate_concepts: list[CandidateConcept]
    candidate_maps: list[CandidateMap]
    source_level_observations: list[str]


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


class ReviewStatus(str, Enum):
    PASS = "PASS"
    FIX = "FIX"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ReviewResult(StrictModel):
    status: ReviewStatus
    issues: list[str]
    corrections: list[NoteChange]
