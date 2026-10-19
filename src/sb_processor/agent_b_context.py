"""Select bounded, page-aware evidence for an independent change review."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from .agent_a import ExistingNoteContext
from .extraction import ProcessingCompleteness
from .models import NoteChange, ProcessingProposal, StrictModel
from .registry import normalize


class SourcePageEvidence(StrictModel):
    page_number: int
    text: str
    visual_extraction: str = ""
    visual_status: str = "NOT_REQUIRED"


class AgentBRequest(StrictModel):
    workflow: str
    proposal_change: NoteChange
    proposal_summary: str
    other_proposed_changes: list[dict[str, str]] = Field(default_factory=list)
    concept_resolution: dict[str, Any] | None = None
    source_metadata: dict[str, str]
    source_evidence: list[SourcePageEvidence]
    visual_evidence: list[dict[str, Any]] = Field(default_factory=list)
    deterministic_findings: list[dict[str, Any]] = Field(default_factory=list)
    source_pages_available: int
    evidence_selection: str
    affected_existing_notes: list[ExistingNoteContext]
    retrieval_evidence: list[dict[str, Any]]
    document_completeness: ProcessingCompleteness | None = None
    review_instructions: str


@dataclass(frozen=True)
class ReviewArtifacts:
    run: Path
    proposal: ProcessingProposal
    agent_a_context: dict[str, Any]
    source_analysis: dict[str, Any]
    retrieval_evidence: list[dict[str, Any]]


def load_review_artifacts(run: Path) -> ReviewArtifacts:
    run = Path(run)
    return ReviewArtifacts(
        run=run,
        proposal=ProcessingProposal.model_validate_json((run / "proposal.json").read_text(encoding="utf-8")),
        agent_a_context=json.loads((run / "request_context.json").read_text(encoding="utf-8")),
        source_analysis=json.loads((run / "source_analysis.json").read_text(encoding="utf-8")),
        retrieval_evidence=json.loads((run / "retrieval_evidence.json").read_text(encoding="utf-8")),
    )


_PAGE = re.compile(r"(?m)^\[Page (\d+)\]\s*$")
_VISUAL = re.compile(r"(?m)^VISUAL CONTENT(?: \(UNRESOLVED\))?:\s*$")


def _pages(source_text: str, visual_statuses: list[dict[str, Any]]) -> dict[int, SourcePageEvidence]:
    markers = list(_PAGE.finditer(source_text))
    statuses = {int(item["page_number"]): str(item["status"]) for item in visual_statuses}
    result = {}
    for index, marker in enumerate(markers):
        number = int(marker.group(1))
        end = markers[index + 1].start() if index + 1 < len(markers) else len(source_text)
        segment = source_text[marker.end():end].strip()
        visual_marker = _VISUAL.search(segment)
        if visual_marker:
            body = segment[:visual_marker.start()].removeprefix("TEXT:").strip()
            visual = segment[visual_marker.end():].strip()
        else:
            body = segment.removeprefix("TEXT:").strip()
            visual = ""
        result[number] = SourcePageEvidence(page_number=number, text=body,
                                            visual_extraction=visual, visual_status=statuses.get(number, "NOT_REQUIRED"))
    return result


def build_review_request(artifacts: ReviewArtifacts, change: NoteChange, instructions: str,
                         *, max_pages: int = 8) -> AgentBRequest:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    context = artifacts.agent_a_context
    pages = _pages(context["source_text"], context.get("visual_page_statuses", []))
    analysis = artifacts.source_analysis
    identified = []
    for kind in ("candidate_concepts", "candidate_maps", "source_note_candidates"):
        identified.extend(analysis.get(kind, []))
    name = normalize(change.title)
    page_numbers = []
    for item in identified:
        candidate = normalize(item.get("proposed_name", ""))
        if candidate == name or (candidate and candidate in name and change.note_type in ("course", "lecture")):
            page_numbers.extend(item.get("source_pages", []))
    selection = "source_analysis provenance"
    if not page_numbers:
        # A title occurrence is only a retrieval hint, never proof of claim support.
        page_numbers = [number for number, page in pages.items() if name and name in normalize(page.text)]
        selection = "title occurrence fallback"
    if not page_numbers and pages:
        page_numbers = [min(pages)]
        selection = "first-page fallback; evidence may be insufficient"
    selected = [pages[number] for number in dict.fromkeys(page_numbers) if number in pages][:max_pages]
    relevant_retrieval = [item for item in artifacts.retrieval_evidence
                          if normalize(item.get("candidate_name", "")) == name]
    related_paths = {change.target_path}
    related_paths.update(match.path for match in change.candidate_existing_notes)
    for item in relevant_retrieval:
        related_paths.update(hit.get("path", "") for hit in item.get("retrieved", []))
    existing = [ExistingNoteContext.model_validate(item) for item in context.get("relevant_existing_notes", [])
                if item.get("path") in related_paths]
    resolution = next((item.model_dump(mode="json") for item in artifacts.proposal.concept_resolutions
                       if normalize(item.candidate_name) == name or item.existing_path == change.target_path), None)
    return AgentBRequest(
        workflow=artifacts.proposal.workflow,
        proposal_change=change,
        proposal_summary=artifacts.proposal.source_summary,
        other_proposed_changes=[{"path": item.target_path, "title": item.title, "note_type": item.note_type,
                                 "action": item.action.value} for item in artifacts.proposal.note_changes
                                if item is not change],
        concept_resolution=resolution,
        source_metadata=context.get("source_metadata", {}),
        source_evidence=selected,
        visual_evidence=[{"page_number": page.page_number, "visual_status": page.visual_status,
                          "original_page_requested": True}
                         for page in selected if page.visual_extraction and page.visual_status == "COMPLETE"],
        source_pages_available=len(pages),
        evidence_selection=selection,
        affected_existing_notes=existing,
        retrieval_evidence=relevant_retrieval,
        document_completeness=artifacts.proposal.source_completeness,
        review_instructions=instructions,
    )
