from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .llm import LLMClient
from .agent_a import build_agent_a_request
from .extraction import ProcessingCompleteness, CompletenessStatus
from .models import Action, LLMProposal, NoteChange, NoteMetadata, ProcessingProposal
from .registry import Registry
from .retrieval import RetrievalPolicy, retrieve_notes, source_candidate_terms
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


def process_source(*, vault_path: Path, source_path: Path, staging_path: Path, database_path: Path, workflow: Workflow, llm: LLMClient, allow_incomplete_visuals: bool = False) -> Path:
    vault = Path(vault_path).resolve(strict=True)
    source = Path(source_path).resolve(strict=True)
    stage = Path(staging_path).resolve()
    database = Path(database_path).resolve()
    if not vault.is_dir() or not source.is_file():
        raise ValueError("Vault must be a directory and source must be a file")
    if not _outside_vault(stage, vault) or not _outside_vault(database, vault):
        raise ValueError("Staging and database paths must be outside the vault")
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
    terms = list(dict.fromkeys([*workflow_context.get("candidate_terms", []),
                                *source_candidate_terms(workflow_context["source_text"], source.name)]))
    retrieval = retrieve_notes(registry, workflow_context["source_text"], terms, policy)
    request, diagnostics = build_agent_a_request(workflow.name, source, workflow_context, retrieval)
    context = request.model_dump(mode="json")
    relevant_paths = set(retrieval.loaded_bodies)
    log.info("Context: %d candidates, %d bodies, %d request characters", len(retrieval.candidates),
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
        if action == Action.CREATE and (target_note or any(c.match_kind in ("exact_title", "exact_filename", "alias", "canonical_name") for c in candidates)):
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
    proposal = ProcessingProposal(workflow=workflow.name, source=str(source), source_summary=draft.source_summary, vault_note_count=note_count, note_changes=changes, review_required=review_items, source_completeness=completeness)
    return stage_proposal(stage, proposal, context, safe_paths, diagnostics)
