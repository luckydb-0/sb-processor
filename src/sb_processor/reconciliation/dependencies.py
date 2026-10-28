from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from ..knowledge.registry import normalize
from ..models import Action
from .identities import IdentityAnalysis, content_identity, is_indexable_identity_path
from .inputs import ReconciliationInputs
from .models import (
    DependencyRecord,
    DependencyTargetState,
    ReconciledChange,
    ReconciledChangeStatus,
    ValidationFinding,
    ValidationSeverity,
)


_WIKILINK = re.compile(r"\[\[([^\[\]\n]+)\]\]")


def _target_text(inner: str) -> str:
    target = inner.split("|", 1)[0].split("#", 1)[0].strip()
    return target.removesuffix(".md")


def _proposed_identities(inputs: ReconciliationInputs,
                         changes: list[ReconciledChange]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for change in changes:
        source = inputs.reviewed_proposal.note_changes[change.agent_a_change_index]
        path = change.final_target_path or change.original_target_path
        if not is_indexable_identity_path(inputs, path, source.note_type):
            continue
        pure_path = PurePosixPath(path)
        content = change.final_content if change.final_content is not None else source.content
        title, aliases = content_identity(content)
        identities = [
            pure_path.with_suffix("").as_posix(),
            pure_path.stem,
            *((title,) if title is not None else ()),
            *aliases,
        ]
        for identity in identities:
            normalized = normalize(identity)
            if normalized:
                result[normalized].add(path)
    return result


def _state_for_target(inputs: ReconciliationInputs,
                      change: ReconciledChange | None,
                      path: str) -> tuple[DependencyTargetState, str | None, str | None]:
    existing = any(note.path == path for note in inputs.vault_notes)
    if change is None:
        return DependencyTargetState.TARGET_EXISTS_IN_VAULT, None, None
    root_decision_id = (
        change.human_decision_ids[0]
        if len(change.human_decision_ids) == 1
        else None
    )
    if change.status in (ReconciledChangeStatus.BLOCKED, ReconciledChangeStatus.DEFERRED):
        if existing and change.original_action is not Action.CREATE:
            return DependencyTargetState.TARGET_EXISTS_IN_VAULT, change.id, root_decision_id
        return DependencyTargetState.TARGET_DEFERRED, change.id, root_decision_id
    if change.status is ReconciledChangeStatus.SKIPPED:
        if existing:
            return DependencyTargetState.TARGET_EXISTS_IN_VAULT, change.id, root_decision_id
        return DependencyTargetState.TARGET_SKIPPED, change.id, root_decision_id
    if change.final_action is Action.CREATE:
        return DependencyTargetState.TARGET_CREATED_IN_BATCH, change.id, root_decision_id
    if change.final_action is Action.UPDATE:
        return DependencyTargetState.TARGET_UPDATED_IN_BATCH, change.id, root_decision_id
    if existing:
        return DependencyTargetState.TARGET_EXISTS_IN_VAULT, change.id, root_decision_id
    return DependencyTargetState.TARGET_SKIPPED, change.id, root_decision_id


def analyze_dependencies(
        inputs: ReconciliationInputs,
        changes: list[ReconciledChange],
        identities: IdentityAnalysis) -> list[DependencyRecord]:
    """Resolve every staged wikilink against effective vault and batch identities."""
    proposed = _proposed_identities(inputs, changes)
    change_by_path = {
        (item.final_target_path or item.original_target_path): item
        for item in changes
    }
    records: list[DependencyRecord] = []
    per_source_count: dict[str, int] = defaultdict(int)

    for source_change in changes:
        if source_change.final_content is None:
            continue
        source_path = source_change.final_target_path or source_change.original_target_path
        for match in _WIKILINK.finditer(source_change.final_content):
            inner = match.group(1)
            target_text = _target_text(inner)
            normalized = normalize(target_text)
            effective_claims = identities.by_normalized.get(normalized, ())
            effective_paths = {item.canonical_path for item in effective_claims}
            proposed_paths = proposed.get(normalized, set())

            if "/" in target_text:
                target_path = f"{target_text}.md"
                all_paths = {
                    item.canonical_path for item in identities.claims
                } | {path for paths in proposed.values() for path in paths}
                candidates = {
                    path for path in all_paths
                    if path == target_path or path.endswith(f"/{target_path}")
                }
            else:
                candidates = effective_paths | proposed_paths

            target_path: str | None = None
            target_change_id: str | None = None
            root_decision_id: str | None = None
            if len(candidates) > 1:
                state = DependencyTargetState.TARGET_AMBIGUOUS
            elif not candidates:
                state = DependencyTargetState.TARGET_MISSING
            else:
                target_path = next(iter(candidates))
                state, target_change_id, root_decision_id = _state_for_target(
                    inputs, change_by_path.get(target_path), target_path
                )
            blocking = state in {
                DependencyTargetState.TARGET_DEFERRED,
                DependencyTargetState.TARGET_SKIPPED,
                DependencyTargetState.TARGET_MISSING,
                DependencyTargetState.TARGET_AMBIGUOUS,
            }
            per_source_count[source_change.id] += 1
            records.append(DependencyRecord(
                id=f"DEP-{source_change.id}-{per_source_count[source_change.id]:02d}",
                source_change_id=source_change.id,
                source_path=source_path,
                token=match.group(0),
                normalized_target=normalized,
                target_state=state,
                target_path=target_path,
                target_change_id=target_change_id,
                blocking=blocking,
                root_decision_id=root_decision_id,
            ))
    return records


def dependency_findings(records: list[DependencyRecord]) -> list[ValidationFinding]:
    return [
        ValidationFinding(
            code="UNRESOLVED_REQUIRED_DEPENDENCY",
            severity=ValidationSeverity.ERROR,
            message=(
                f"{record.token} resolves as {record.target_state.value}"
                + (f" via {record.target_path}" if record.target_path else "")
            ),
            change_ids=[record.source_change_id],
        )
        for record in records
        if record.blocking
    ]
