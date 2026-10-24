from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Action, DraftChange, NoteMetadata, ProcessingProposal
from .agent_a import ContextDiagnostics
from .knowledge.registry import normalize

log = logging.getLogger(__name__)


def audit_wikilinks(changes: list[DraftChange], metadata: list[NoteMetadata]) -> list[dict[str, str]]:
    """Report links without blocking staging or assuming unresolved names are new notes."""
    existing: dict[str, str] = {}
    for note in metadata:
        for name in [note.path.removesuffix(".md"), note.filename.removesuffix(".md"), note.title, *note.aliases]:
            existing.setdefault(normalize(name), note.path)
    created = {normalize(change.title): change.target_path for change in changes if change.action == Action.CREATE}
    created.update({normalize(change.target_path.removesuffix(".md")): change.target_path
                    for change in changes if change.action == Action.CREATE})
    result = []
    for change in changes:
        for raw in re.findall(r"\[\[([^\]]+)\]\]", change.content):
            target = raw.split("|", 1)[0].split("#", 1)[0].strip()
            key = normalize(target.removesuffix(".md"))
            if key in existing:
                status, path = "existing note", existing[key]
            elif key in created:
                status, path = "created in same proposal", created[key]
            else:
                status, path = "unresolved / ghost link", ""
            result.append({"from": change.target_path, "target": target, "status": status,
                           "resolved_path": path})
    return result


def stage_proposal(staging_path: Path, proposal: ProcessingProposal, context: dict[str, Any], safe_paths: list[bool],
                   diagnostics: ContextDiagnostics, *, pass1_context: dict[str, Any] | None = None,
                   pass1_diagnostics: ContextDiagnostics | None = None, source_analysis: dict[str, Any] | None = None,
                   discovery_selection: dict[str, Any] | None = None,
                   retrieval_evidence: list[dict[str, Any]] | None = None,
                   semantic_stats: dict[str, Any] | None = None,
                   wikilink_audit: list[dict[str, str]] | None = None) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run = Path(staging_path) / f"run_{run_id}"
    notes_dir = run / "notes"
    notes_dir.mkdir(parents=True)
    (run / "proposal.json").write_text(proposal.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (run / "request_context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (run / "context_diagnostics.json").write_text(json.dumps(asdict(diagnostics), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if pass1_context is not None:
        (run / "pass1_request.json").write_text(json.dumps(pass1_context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if pass1_diagnostics is not None:
        (run / "pass1_diagnostics.json").write_text(json.dumps(asdict(pass1_diagnostics), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if source_analysis is not None:
        (run / "source_analysis.json").write_text(json.dumps(source_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if discovery_selection is not None:
        (run / "discovery_selection.json").write_text(json.dumps(discovery_selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if retrieval_evidence is not None:
        (run / "retrieval_evidence.json").write_text(json.dumps(retrieval_evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if semantic_stats is not None:
        (run / "semantic_diagnostics.json").write_text(json.dumps(semantic_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if wikilink_audit is not None:
        (run / "wikilinks.json").write_text(json.dumps(wikilink_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Processing review", "", f"Workflow: `{proposal.workflow}`", f"Source: `{proposal.source}`", f"Vault notes scanned: {proposal.vault_note_count}", "", "No vault files were written.", ""]
    used: set[str] = set()
    for index, change in enumerate(proposal.note_changes, 1):
        lines += [f"## {index}. {change.action.value}: {change.title}", "", f"Target: `{change.target_path}`", f"Reason: {change.reason}", ""]
        if change.original_content_hash:
            lines += [f"Existing content SHA-256: `{change.original_content_hash}`", ""]
        if change.candidate_existing_notes:
            lines += ["Candidates:", ""]
            for candidate in change.candidate_existing_notes:
                lines.append(f"- `{candidate.path}` ({candidate.match_kind}, {candidate.score:.2f})")
            lines.append("")
        if safe_paths[index - 1] and change.content.strip() and change.action != Action.NO_CHANGE:
            if change.target_path not in used:
                output = notes_dir / change.target_path
                used.add(change.target_path)
            else:
                output = run / "conflicts" / f"draft_{index:03d}.md"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(change.content.rstrip() + "\n", encoding="utf-8")
            lines += [f"Staged Markdown: `{output.relative_to(run).as_posix()}`", ""]
    if proposal.review_required:
        lines += ["## Review items", ""] + [f"- {item}" for item in proposal.review_required] + [""]
    if proposal.concept_resolutions:
        lines += ["## Concept resolutions", ""]
        for item in proposal.concept_resolutions:
            lines.append(f"- **{item.candidate_name}**: {item.relation.value}; existing: `{item.existing_path or 'none'}`; {item.reason}")
        lines.append("")
    if discovery_selection is not None:
        lines += ["## Discovery selection", "", f"Selected {len(discovery_selection['selected'])} of {len(discovery_selection['selected']) + len(discovery_selection['omitted'])} candidate concepts (cap {discovery_selection['max_candidate_concepts']}).", ""]
        if discovery_selection.get("deterministic_added"):
            lines += ["Explicit definition headings added deterministically: " + ", ".join(discovery_selection["deterministic_added"]), ""]
        if discovery_selection["omitted"]:
            lines += ["Omitted for review: " + ", ".join(discovery_selection["omitted"]), ""]
    lines += ["## Context diagnostics", "",
              f"Instructions: {diagnostics.instruction_chars} characters; templates: {diagnostics.template_chars}; source: {diagnostics.source_chars}; existing note bodies: {diagnostics.existing_note_chars}",
              f"Candidates considered: {diagnostics.candidate_notes_considered}; selected: {diagnostics.candidate_notes_selected}; full bodies loaded: {diagnostics.full_note_bodies_loaded}",
              f"Serialized request: {diagnostics.total_request_chars} characters (~{diagnostics.estimated_tokens} tokens)", ""]
    if pass1_diagnostics is not None:
        lines += [f"Pass 1 request: {pass1_diagnostics.total_request_chars} characters (~{pass1_diagnostics.estimated_tokens} tokens); existing note bodies: {pass1_diagnostics.existing_note_chars}", ""]
    if semantic_stats is not None:
        lines += ["## Semantic index", "", f"Model: `{semantic_stats.get('model', '')}`; indexed: {semantic_stats.get('indexed', 0)}; embedded: {semantic_stats.get('embedded', 0)}; reused: {semantic_stats.get('reused', 0)}; updated: {semantic_stats.get('updated', 0)}; deleted: {semantic_stats.get('deleted', 0)}", ""]
    if retrieval_evidence is not None:
        lines += ["## Candidate retrieval evidence", ""]
        for item in retrieval_evidence:
            lines += [f"### {item['candidate_name']}", ""]
            for candidate in item["retrieved"]:
                lines.append(f"- `{candidate['path']}`: {', '.join(candidate['retrieval_methods'])}; lexical={candidate['lexical_score']}; semantic={candidate['semantic_score']}; body={'yes' if candidate['path'] in item['loaded_body_paths'] else 'no'}")
            for observation in item["semantic_observations"]:
                lines.append(f"  - semantic observed `{observation['path']}`: {observation['score']:.3f} ({'above' if observation['above_threshold'] else 'below'} threshold)")
            lines.append("")
    if wikilink_audit is not None:
        lines += ["## Wikilinks", ""]
        lines.extend(f"- `{item['from']}` → `[[{item['target']}]]`: {item['status']}"
                     for item in wikilink_audit)
        lines.append("")
    if diagnostics.selected:
        lines += ["Selected candidates:", ""] + [f"- `{item['path']}`: {item['reason']}; body loaded: {item['body_loaded']}" for item in diagnostics.selected] + [""]
    if diagnostics.excluded:
        lines += ["Excluded by retrieval policy:", ""] + [f"- `{item.path}`: {item.reason}" for item in diagnostics.excluded] + [""]
    (run / "review.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("Staged proposal at %s", run)
    return run
