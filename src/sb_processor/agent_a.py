"""Typed Agent A request and observable context assembly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from .extraction import ProcessingCompleteness
from .models import CandidateMatch, SourceAnalysis, StrictModel
from .retrieval import CandidateRetrieval, ExcludedNote, RetrievalResult


class ExistingNoteContext(StrictModel):
    path: str
    title: str
    note_type: str | None
    body: str


class AgentARequest(StrictModel):
    workflow: str
    source_metadata: dict[str, str]
    source_text: str
    document_completeness: ProcessingCompleteness | None = None
    incomplete_visuals_override: bool = False
    visual_page_statuses: list[dict[str, Any]] = Field(default_factory=list)
    workflow_instructions: str = ""
    workflow_prompt: str = ""
    templates: str = ""
    suggested_note_roots: dict[str, str] = Field(default_factory=dict)
    candidate_existing_notes: list[CandidateMatch] = Field(default_factory=list)
    relevant_existing_notes: list[ExistingNoteContext] = Field(default_factory=list)
    retrieval_limitation: str
    path_instruction: str
    source_analysis: SourceAnalysis | None = None
    candidate_evidence: list[dict[str, Any]] = Field(default_factory=list)


class AgentADiscoveryRequest(StrictModel):
    workflow: str
    source_metadata: dict[str, str]
    source_text: str
    document_completeness: ProcessingCompleteness | None = None
    incomplete_visuals_override: bool = False
    visual_page_statuses: list[dict[str, Any]] = Field(default_factory=list)
    workflow_instructions: str = ""
    workflow_prompt: str = ""
    candidate_terms: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ContextDiagnostics:
    instruction_chars: int
    template_chars: int
    source_chars: int
    existing_note_chars: int
    candidate_metadata_chars: int
    total_request_chars: int
    estimated_tokens: int
    candidate_notes_considered: int
    candidate_notes_selected: int
    full_note_bodies_loaded: int
    full_note_bodies_skipped: list[str]
    selected: list[dict[str, str]]
    excluded: list[ExcludedNote]


PATH_INSTRUCTION = (
    "All target_path values must be relative .md paths within the vault and use the workflow's note roots. "
    "Candidate metadata is evidence for possible equivalence, not proof. A missing deterministic match is not proof "
    "that no equivalent note exists. UPDATE only when the target's complete existing body is supplied; otherwise "
    "use REVIEW_REQUIRED. For supplied existing-note bodies, explicitly return NO_CHANGE when the source adds no "
    "useful evidence, UPDATE when it does, or REVIEW_REQUIRED when boundaries remain unclear. Return complete "
    "Markdown content for CREATE/UPDATE."
)


def build_discovery_request(workflow: str, source: Path, prepared: dict[str, Any]
                            ) -> tuple[AgentADiscoveryRequest, ContextDiagnostics]:
    request = AgentADiscoveryRequest(
        workflow=workflow,
        source_metadata={"filename": source.name, "path": str(source), "extractor": str(prepared.get("pdf_extractor", ""))},
        source_text=prepared["source_text"],
        document_completeness=prepared.get("document_completeness"),
        incomplete_visuals_override=bool(prepared.get("incomplete_visuals_override", False)),
        visual_page_statuses=prepared.get("visual_page_statuses", []),
        workflow_instructions=prepared.get("workflow_instructions", prepared.get("instructions", "")),
        workflow_prompt=prepared.get("workflow_prompt", ""),
        candidate_terms=prepared.get("candidate_terms", []),
    )
    serialized = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
    return request, ContextDiagnostics(
        instruction_chars=len(request.workflow_instructions) + len(request.workflow_prompt),
        template_chars=0, source_chars=len(request.source_text), existing_note_chars=0,
        candidate_metadata_chars=0, total_request_chars=len(serialized), estimated_tokens=(len(serialized)+3)//4,
        candidate_notes_considered=0, candidate_notes_selected=0, full_note_bodies_loaded=0,
        full_note_bodies_skipped=[], selected=[], excluded=[])


def build_agent_a_request(workflow: str, source: Path, prepared: dict[str, Any],
                          retrieval: RetrievalResult) -> tuple[AgentARequest, ContextDiagnostics]:
    candidates = retrieval.candidates
    request = AgentARequest(
        workflow=workflow,
        source_metadata={"filename": source.name, "path": str(source), "extractor": str(prepared.get("pdf_extractor", ""))},
        source_text=prepared["source_text"],
        document_completeness=prepared.get("document_completeness"),
        incomplete_visuals_override=bool(prepared.get("incomplete_visuals_override", False)),
        visual_page_statuses=prepared.get("visual_page_statuses", []),
        workflow_instructions=prepared.get("workflow_instructions", prepared.get("instructions", "")),
        workflow_prompt=prepared.get("workflow_prompt", ""),
        templates=prepared.get("templates", ""),
        suggested_note_roots=prepared.get("suggested_note_roots", {}),
        candidate_existing_notes=candidates,
        relevant_existing_notes=[ExistingNoteContext(path=c.path, title=c.title, note_type=c.note_type,
                                                      body=retrieval.loaded_bodies[c.path])
                                 for c in candidates if c.path in retrieval.loaded_bodies],
        retrieval_limitation=retrieval.limitation,
        path_instruction=PATH_INSTRUCTION,
    )
    payload = request.model_dump(mode="json")
    candidate_json = json.dumps(payload["candidate_existing_notes"], ensure_ascii=False)
    serialized = json.dumps(payload, ensure_ascii=False)
    diagnostics = ContextDiagnostics(
        instruction_chars=len(request.workflow_instructions) + len(request.workflow_prompt) + len(request.path_instruction),
        template_chars=len(request.templates), source_chars=len(request.source_text),
        existing_note_chars=sum(len(n.body) for n in request.relevant_existing_notes),
        candidate_metadata_chars=len(candidate_json), total_request_chars=len(serialized),
        estimated_tokens=(len(serialized) + 3) // 4,
        candidate_notes_considered=retrieval.considered, candidate_notes_selected=len(candidates),
        full_note_bodies_loaded=len(retrieval.loaded_bodies),
        full_note_bodies_skipped=retrieval.skipped_bodies,
        selected=[{"path": c.path, "reason": c.match_kind, "body_loaded": str(c.path in retrieval.loaded_bodies).lower(),
                   "body_status": "size limit" if c.path in retrieval.skipped_bodies else "selected" if c.path in retrieval.loaded_bodies else "rank limit"}
                  for c in candidates],
        excluded=retrieval.excluded,
    )
    return request, diagnostics


def build_resolution_request(workflow: str, source: Path, prepared: dict[str, Any],
                             analysis: SourceAnalysis, retrievals: list[CandidateRetrieval]
                             ) -> tuple[AgentARequest, ContextDiagnostics]:
    """Assemble one pass-2 request from independent bounded candidate searches."""
    unique = {}
    bodies = {}
    excluded = {}
    skipped = []
    for result in retrievals:
        for candidate in result.candidates:
            unique.setdefault(candidate.path, candidate)
        bodies.update(result.loaded_bodies)
        for item in result.excluded:
            excluded[item.path] = item
        skipped.extend(result.skipped_bodies)
    aggregate = RetrievalResult(candidates=list(unique.values()), loaded_bodies=bodies,
                                excluded=list(excluded.values()), considered=sum(r.considered for r in retrievals),
                                skipped_bodies=list(dict.fromkeys(skipped)))
    request, diagnostics = build_agent_a_request(workflow, source, prepared, aggregate)
    request.source_analysis = analysis
    request.candidate_evidence = [
        {"candidate_name": result.candidate_name,
         "retrieved": [item.model_dump(mode="json") for item in result.candidates],
         "semantic_observations": [vars(item) for item in result.semantic_observations],
         "loaded_body_paths": list(result.loaded_bodies), "skipped_body_paths": result.skipped_bodies}
        for result in retrievals]
    payload = request.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False)
    diagnostics = ContextDiagnostics(**{**vars(diagnostics),
        "candidate_metadata_chars": len(json.dumps(payload["candidate_evidence"], ensure_ascii=False)),
        "total_request_chars": len(serialized), "estimated_tokens": (len(serialized)+3)//4})
    return request, diagnostics
