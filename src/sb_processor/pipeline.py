from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .llm import LLMClient
from .agent_a import build_discovery_request, build_resolution_request
from .extraction import ProcessingCompleteness, CompletenessStatus
from .models import Action, LLMProposal, NoteChange, NoteMetadata, ProcessingProposal, SourceAnalysis
from .registry import Registry
from .retrieval import RetrievalPolicy, retrieve_candidate, retrieve_notes
from .semantic import DEFAULT_EMBEDDING_MODEL, SemanticIndex
from .staging import stage_proposal
from .vault import scan_vault

log = logging.getLogger(__name__)


class Workflow(Protocol):
    name: str

    def prepare(self, source: Path, vault: Path) -> dict[str, Any]:
        ...


class IncompleteDocumentError(ValueError):
    def __init__(self, completeness: ProcessingCompleteness):
        self.completeness = completeness
        super().__init__(f"Document is PARTIAL; text extraction complete: {completeness.text_extraction_complete}; "
                         f"unresolved visual pages: {completeness.unprocessed_visual_pages}. "
                         "Use --allow-incomplete-visuals only for unresolved visual pages and qualified proposals.")


def _outside_vault(path: Path, vault: Path) -> bool:
    return not path.resolve().is_relative_to(vault.resolve())


def _safe_target(target: str, vault: Path) -> bool:
    if not target or "\\" in target or PurePosixPath(target).is_absolute():
        return False
    parts = PurePosixPath(target).parts
    if not parts or any(part in (".", "..") for part in parts) or not target.endswith(".md"):
        return False
    return (vault / target).resolve().is_relative_to(vault)


def process_source(*, vault_path: Path, source_path: Path, staging_path: Path, database_path: Path,
                   workflow: Workflow, llm: LLMClient, allow_incomplete_visuals: bool = False,
                   semantic_index: Any = None, semantic_stats: dict[str, Any] | None = None,
                   semantic_index_path: Path | None = None, embedding_model: str = DEFAULT_EMBEDDING_MODEL,
                   embedding_cache: Path | None = None, candidate_top_k: int = 4,
                   semantic_threshold: float = 0.55) -> Path:
    vault = Path(vault_path).resolve(strict=True)
    source = Path(source_path).resolve(strict=True)
    stage = Path(staging_path).resolve()
    database = Path(database_path).resolve()
    if not vault.is_dir() or not source.is_file():
        raise ValueError("Vault must be a directory and source must be a file")
    if not _outside_vault(stage, vault) or not _outside_vault(database, vault):
        raise ValueError("Staging and database paths must be outside the vault")
    if semantic_index_path is not None and not _outside_vault(Path(semantic_index_path), vault):
        raise ValueError("Semantic index path must be outside the vault")
    if embedding_cache is not None and not _outside_vault(Path(embedding_cache), vault):
        raise ValueError("Embedding cache path must be outside the vault")
    registry = Registry(database)
    note_count = registry.rebuild(scan_vault(vault))
    log.info("Registry rebuilt from %d Markdown notes", note_count)
    workflow_context = workflow.prepare(source, vault)
    completeness = (ProcessingCompleteness.model_validate(workflow_context["document_completeness"])
                    if "document_completeness" in workflow_context else None)
    if completeness and completeness.status == CompletenessStatus.PARTIAL and (
        not completeness.text_extraction_complete or not allow_incomplete_visuals
    ):
        raise IncompleteDocumentError(completeness)
    workflow_context["incomplete_visuals_override"] = bool(
        allow_incomplete_visuals and completeness and completeness.status == CompletenessStatus.PARTIAL)
    if "source_text" not in workflow_context:
        raise ValueError("Workflow context must contain source_text")
    policy_factory = getattr(workflow, "retrieval_policy", None)
    policy = policy_factory(vault, workflow_context) if callable(policy_factory) else RetrievalPolicy(
        roots=workflow_context.get("suggested_note_roots") or {"concept": "Dots", "map": "Maps"})
    discovery_request, discovery_diagnostics = build_discovery_request(workflow.name, source, workflow_context)
    discovery_context = discovery_request.model_dump(mode="json")
    try:
        analysis = SourceAnalysis.model_validate(llm.analyze_source(context=discovery_context))
    except Exception:
        log.exception("Structured source discovery or validation failed")
        raise
    owned_index = None
    try:
        if semantic_index is None and semantic_index_path is not None:
            owned_index = SemanticIndex(semantic_index_path, model_name=embedding_model,
                                        model_cache=embedding_cache)
            semantic_index = owned_index
            semantic_stats = asdict(owned_index.sync(registry, policy))
        retrievals = [retrieve_candidate(registry, candidate.proposed_name, candidate.aliases_or_terms_seen,
                                         policy, semantic_index, top_k=candidate_top_k,
                                         threshold=semantic_threshold)
                      for candidate in analysis.candidate_concepts]
        retrievals.extend(retrieve_candidate(registry, candidate.proposed_name, [], policy, None,
                                             note_type="map", top_k=candidate_top_k)
                          for candidate in analysis.candidate_maps)
    finally:
        if owned_index is not None:
            owned_index.close()
    if semantic_stats is not None:
        semantic_stats.update({"query_count": sum(len({r.candidate_name}) for r in retrievals if r.candidate_name != "course context"),
                               "threshold": semantic_threshold, "top_k_per_candidate": candidate_top_k})
    # Workflow-level course context stays separate from Concept Note equivalence searches.
    course_terms = workflow_context.get("candidate_terms", [])
    if course_terms:
        course_result = retrieve_notes(registry, "", course_terms, policy)
        course_result.candidates = [c for c in course_result.candidates if c.note_type in ("course", "lecture")]
        course_result.loaded_bodies = {path: body for path, body in course_result.loaded_bodies.items()
                                       if any(c.path == path for c in course_result.candidates)}
        if course_result.candidates:
            from .retrieval import CandidateRetrieval
            retrievals.append(CandidateRetrieval(**vars(course_result), candidate_name="course context"))
    request, diagnostics = build_resolution_request(workflow.name, source, workflow_context, analysis, retrievals)
    context = request.model_dump(mode="json")
    relevant_paths = {path for result in retrievals for path in result.loaded_bodies}
    log.info("Pass 1: %d concepts; Pass 2: %d candidates, %d bodies, %d request characters",
             len(analysis.candidate_concepts), len(request.candidate_existing_notes),
             len(relevant_paths), diagnostics.total_request_chars)
    try:
        draft = LLMProposal.model_validate(llm.generate_processing_proposal(context=context))
    except Exception:
        log.exception("Structured proposal generation or validation failed")
        raise
    changes = []
    review_items = list(draft.review_required)
    if completeness and completeness.status == CompletenessStatus.PARTIAL:
        review_items.append(f"Source is PARTIAL; unresolved visual pages: {completeness.unprocessed_visual_pages}")
    safe_paths = []
    seen_paths: set[str] = set()
    for item in draft.note_changes:
        candidates = [c for c in retrieve_notes(registry, "", [item.title], policy, load_bodies=False).candidates
                      if c.note_type == item.note_type]
        log.info("Lookup %r: %s", item.title, [(c.path, c.match_kind) for c in candidates])
        target_meta = NoteMetadata(path=item.target_path, filename=PurePosixPath(item.target_path).name,
                                   title=item.title, note_type=item.note_type, aliases=[], maps=[])
        safe = _safe_target(item.target_path, vault) and policy.kind(target_meta) == item.note_type
        safe_paths.append(safe)
        target_note = registry.get(item.target_path) if safe else None
        action = item.action
        reasons = []
        if not safe:
            reasons.append("Unsafe target path")
        if item.target_path in seen_paths:
            reasons.append("Duplicate proposed target path")
        seen_paths.add(item.target_path)
        if action == Action.CREATE and (target_note or any(c.match_kind in ("exact_title", "exact_filename", "alias", "canonical_name", "normalized_variant") for c in candidates)):
            reasons.append("Existing path or candidate note needs equivalence review")
        if action == Action.UPDATE and not target_note:
            reasons.append("UPDATE target does not exist in the current vault")
        if action == Action.UPDATE and target_note and item.target_path not in relevant_paths:
            reasons.append("UPDATE target content was not sent to the model")
        if action in (Action.CREATE, Action.UPDATE) and not item.content.strip():
            reasons.append("CREATE/UPDATE has no Markdown content")
        if completeness and completeness.status == CompletenessStatus.PARTIAL and action in (Action.CREATE, Action.UPDATE):
            reasons.append(f"Source is PARTIAL; unresolved visual pages: {completeness.unprocessed_visual_pages}")
        if reasons:
            action = Action.REVIEW_REQUIRED
            review_items.append(f"{item.title}: {'; '.join(reasons)}")
        change = NoteChange(**item.model_dump(exclude={"action"}), action=action, candidate_existing_notes=candidates, original_content_hash=target_note.content_hash if target_note else None)
        changes.append(change)
        log.info("Proposed action %s for %s -> %s", action.value, item.title, item.target_path)
    for path in sorted(relevant_paths - seen_paths):
        review_items.append(f"Existing note body was supplied but no decision returned: {path}")
    discovered_names = {candidate.proposed_name.casefold() for candidate in analysis.candidate_concepts}
    resolved_names = {item.candidate_name.casefold() for item in draft.concept_resolutions}
    for missing in sorted(discovered_names - resolved_names):
        review_items.append(f"No explicit concept resolution returned for discovered candidate: {missing}")
    proposal = ProcessingProposal(workflow=workflow.name, source=str(source), source_summary=draft.source_summary,
                                  vault_note_count=note_count, note_changes=changes, review_required=review_items,
                                  source_completeness=completeness, concept_resolutions=draft.concept_resolutions)
    return stage_proposal(stage, proposal, context, safe_paths, diagnostics,
                          pass1_context=discovery_context, pass1_diagnostics=discovery_diagnostics,
                          source_analysis=analysis.model_dump(mode="json"),
                          retrieval_evidence=context["candidate_evidence"], semantic_stats=semantic_stats)
