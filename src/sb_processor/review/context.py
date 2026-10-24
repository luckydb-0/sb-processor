"""Select bounded, page-aware evidence for an independent change review."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field
import yaml

from ..processing.agent_a import ExistingNoteContext
from ..documents.extraction import ProcessingCompleteness
from ..models import Action, CandidateMatch, NoteChange, ProcessingProposal, ReviewCategory, StrictModel
from .checks import required_checks
from ..knowledge.registry import normalize


class SourcePageEvidence(StrictModel):
    page_number: int
    text: str
    visual_extraction: str = ""
    visual_status: str = "NOT_REQUIRED"


class ProposedReviewChange(StrictModel):
    action: Action
    note_type: str
    title: str
    target_path: str
    reason: str
    proposed_final_content: str
    sources: list[str]
    candidate_existing_notes: list[CandidateMatch]
    original_content_hash: str | None


class ExistingReviewNote(StrictModel):
    path: str
    title: str
    note_type: str | None
    existing_content: str
    review_role: str


class AgentBRequest(StrictModel):
    workflow: str
    proposal_change: ProposedReviewChange
    proposal_summary: str
    other_proposed_changes: list[dict[str, str]] = Field(default_factory=list)
    concept_resolution: dict[str, Any] | None = None
    source_metadata: dict[str, str]
    source_evidence: list[SourcePageEvidence]
    visual_evidence: list[dict[str, Any]] = Field(default_factory=list)
    deterministic_findings: list[dict[str, Any]] = Field(default_factory=list)
    semantic_prechecks: list[dict[str, Any]] = Field(default_factory=list)
    aliases_to_review: list[str] = Field(default_factory=list)
    requires_promotion_assessment: bool = False
    source_pages_available: int
    evidence_selection: str
    affected_existing_notes: list[ExistingReviewNote]
    retrieval_evidence: list[dict[str, Any]]
    document_completeness: ProcessingCompleteness | None = None
    review_instructions: str
    required_checks: list[ReviewCategory]


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
    analysis_key = {"concept": "candidate_concepts", "map": "candidate_maps",
                    "course": "source_note_candidates", "lecture": "source_note_candidates"}.get(change.note_type)
    identified = [item for item in analysis.get(analysis_key, [])
                  if analysis_key != "source_note_candidates" or item.get("note_type") == change.note_type]
    name = normalize(change.title)
    page_numbers = []
    references = [match.group(1) for match in re.finditer(
        r"(?im)^\s*\*{0,2}(?:Relevant )?Pages/slides:\*{0,2}\s*([^\n]+)", change.content)]
    if change.note_type == "lecture":
        references.extend(match.group(1) for match in re.finditer(
            r"\bpp?\.\s*([\d,\s–-]+)", change.content))
    for reference in references:
        for number_range in re.finditer(r"\b(\d+)(?:\s*[-–]\s*(\d+))?\b", reference):
            first = int(number_range.group(1))
            last = int(number_range.group(2) or first)
            if 0 < first <= last and last - first <= 60:
                page_numbers.extend(range(first, last + 1))
    explicit_pages = bool(page_numbers)
    for item in identified:
        candidate = normalize(item.get("proposed_name", ""))
        candidate_words = set(candidate.split())
        title_words = set(name.split())
        overlapping_name = (change.note_type == "concept" and len(candidate_words) >= 2
                            and len(candidate_words & title_words) / len(candidate_words) >= 0.66)
        if candidate == name or overlapping_name or (candidate and candidate in name and change.note_type in ("course", "lecture")):
            page_numbers.extend(item.get("source_pages", []))
    selection = "explicit note page reference and source_analysis provenance" if explicit_pages else "source_analysis provenance"
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
    existing = [ExistingReviewNote(path=note.path, title=note.title, note_type=note.note_type,
                                  existing_content=note.body,
                                  review_role="pre_update_target" if change.action == Action.UPDATE and
                                      note.path == change.target_path else "related_existing_note")
                for item in context.get("relevant_existing_notes", [])
                if item.get("path") in related_paths
                for note in [ExistingNoteContext.model_validate(item)]]
    resolution = next((item.model_dump(mode="json") for item in artifacts.proposal.concept_resolutions
                       if normalize(item.candidate_name) == name or item.existing_path == change.target_path), None)
    aliases: list[str] = []
    if change.content.startswith("---\n"):
        frontmatter = change.content.split("\n---", 1)[0].removeprefix("---\n")
        try:
            parsed = yaml.safe_load(frontmatter)
            if isinstance(parsed, dict) and isinstance(parsed.get("aliases"), list):
                aliases = [value for value in parsed["aliases"] if isinstance(value, str)]
        except yaml.YAMLError:
            pass
    if not aliases and change.action == Action.NO_CHANGE:
        aliases = [alias for match in change.candidate_existing_notes if match.path == change.target_path
                   for alias in match.aliases]
    return AgentBRequest(
        workflow=artifacts.proposal.workflow,
        proposal_change=ProposedReviewChange.model_validate({
            **change.model_dump(exclude={"content"}), "proposed_final_content": change.content}),
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
        aliases_to_review=aliases,
        requires_promotion_assessment=change.note_type == "concept" and change.action == Action.CREATE,
        source_pages_available=len(pages),
        evidence_selection=selection,
        affected_existing_notes=existing,
        retrieval_evidence=relevant_retrieval,
        document_completeness=artifacts.proposal.source_completeness,
        review_instructions=instructions,
        required_checks=required_checks(change.note_type),
    )
