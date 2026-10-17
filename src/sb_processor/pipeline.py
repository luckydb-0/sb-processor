from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .llm import LLMClient
from .models import Action, NoteChange, ProcessingProposal
from .registry import Registry
from .staging import stage_proposal
from .vault import scan_vault

log = logging.getLogger(__name__)


class Workflow(Protocol):
    name: str

    def prepare(self, source: Path, vault: Path) -> dict[str, Any]:
        ...


def _outside_vault(path: Path, vault: Path) -> bool:
    return not path.resolve().is_relative_to(vault.resolve())


def _safe_target(target: str, vault: Path) -> bool:
    if not target or "\\" in target or PurePosixPath(target).is_absolute():
        return False
    parts = PurePosixPath(target).parts
    if not parts or any(part in (".", "..") for part in parts) or not target.endswith(".md"):
        return False
    return (vault / target).resolve().is_relative_to(vault)


def process_source(*, vault_path: Path, source_path: Path, staging_path: Path, database_path: Path, workflow: Workflow, llm: LLMClient) -> Path:
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
    if "source_text" not in workflow_context:
        raise ValueError("Workflow context must contain source_text")
    inventory = [{"path": n.path, "title": n.title, "note_type": n.note_type, "aliases": n.aliases} for n in registry.all_notes()]
    relevant = registry.relevant(workflow_context["source_text"])
    relevant_paths = {note.path for note in relevant}
    context = {
        "workflow": workflow.name,
        "source_filename": source.name,
        **workflow_context,
        "vault_inventory": inventory,
        "relevant_existing_notes": [{"path": n.path, "title": n.title, "note_type": n.note_type, "frontmatter": n.frontmatter, "body": n.body[:6000]} for n in relevant],
        "path_instruction": "All target_path values must be relative .md paths within the vault. Use only the workflow's note types and conventions. If a possible equivalent note exists, prefer REVIEW_REQUIRED or a conservative UPDATE with its exact path. Include a complete proposed Markdown file for CREATE/UPDATE.",
    }
    log.info("Context: %d inventory entries, %d relevant notes, %d source characters", len(inventory), len(relevant), len(workflow_context["source_text"]))
    try:
        draft = llm.generate_processing_proposal(context=context)
    except Exception:
        log.exception("Structured proposal generation or validation failed")
        raise
    changes = []
    review_items = list(draft.review_required)
    safe_paths = []
    seen_paths: set[str] = set()
    for item in draft.note_changes:
        candidates = registry.lookup(item.title)
        log.info("Lookup %r: %s", item.title, [(c.path, c.match_kind) for c in candidates])
        safe = _safe_target(item.target_path, vault)
        safe_paths.append(safe)
        target_note = registry.get(item.target_path) if safe else None
        action = item.action
        reasons = []
        if not safe:
            reasons.append("Unsafe target path")
        if item.target_path in seen_paths:
            reasons.append("Duplicate proposed target path")
        seen_paths.add(item.target_path)
        if action == Action.CREATE and (target_note or candidates):
            reasons.append("Existing path or candidate note needs equivalence review")
        if action == Action.UPDATE and not target_note:
            reasons.append("UPDATE target does not exist in the current vault")
        if action == Action.UPDATE and target_note and item.target_path not in relevant_paths:
            reasons.append("UPDATE target content was not sent to the model")
        if action in (Action.CREATE, Action.UPDATE) and not item.content.strip():
            reasons.append("CREATE/UPDATE has no Markdown content")
        if reasons:
            action = Action.REVIEW_REQUIRED
            review_items.append(f"{item.title}: {'; '.join(reasons)}")
        change = NoteChange(**item.model_dump(exclude={"action"}), action=action, candidate_existing_notes=candidates, original_content_hash=target_note.content_hash if target_note else None)
        changes.append(change)
        log.info("Proposed action %s for %s -> %s", action.value, item.title, item.target_path)
    proposal = ProcessingProposal(workflow=workflow.name, source=str(source), source_summary=draft.source_summary, vault_note_count=note_count, note_changes=changes, review_required=review_items)
    return stage_proposal(stage, proposal, context, safe_paths)
