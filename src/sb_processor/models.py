from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

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


class Action(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    NO_CHANGE = "NO_CHANGE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


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
