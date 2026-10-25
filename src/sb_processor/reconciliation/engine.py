from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..models import Action, NoteChange, ReviewStatus
from .fixes import classify_and_apply_fix
from .inputs import ReconciliationInputs
from .models import (
    DecisionEffect,
    DecisionOption,
    DecisionStatus,
    FinalChangeSet,
    FinalChangeSetState,
    HumanDecision,
    IssueOutcome,
    IssueClassification,
    ReconciledChange,
    ReconciledChangeStatus,
    ReconciledIssue,
    ReconciliationResult,
    ValidationSeverity,
)
from .validators import validate_final_changes


RECONCILIATION_VERSION = "reconciliation-v1"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _existing_content(inputs: ReconciliationInputs, path: str) -> str | None:
    target = inputs.vault / path
    return target.read_text(encoding="utf-8") if target.is_file() else None


def _known_targets(inputs: ReconciliationInputs) -> set[str]:
    paths = {note.path.removesuffix(".md") for note in inputs.vault_notes}
    paths.update(change.target_path.removesuffix(".md") for change in inputs.reviewed_proposal.note_changes)
    return paths


def _decision(decision_id: str, change_id: str, issue: ReconciledIssue,
              change: NoteChange) -> HumanDecision:
    unresolved_link = re.search(r"Unresolved wikilink: (\[\[[^\]]+\]\])", issue.explanation)
    if unresolved_link:
        question = f"Should `{change.target_path}` keep the unresolved wikilink `{unresolved_link.group(1)}`?"
    elif issue.issue_type.value == "alias":
        question = f"Should `{change.target_path}` keep the alias questioned by Agent B?"
    elif issue.issue_type.value in ("concept_boundary", "existing_note"):
        question = f"Should `{change.target_path}` be applied as the separate change Agent A proposed?"
    elif issue.issue_type.value == "cumulative_integrity":
        question = f"Should `{change.target_path}` proceed even though it does not preserve all existing useful content?"
    else:
        question = f"Should `{change.target_path}` proceed with this unresolved {issue.issue_type.value} issue?"
    return HumanDecision(
        id=decision_id,
        change_ids=[change_id],
        issue_ids=[issue.id],
        category=issue.issue_type.value,
        status=DecisionStatus.PENDING,
        question=question,
        context=issue.explanation,
        agent_a_position=f"{change.action.value}: {change.reason}",
        agent_b_position=issue.proposed_correction,
        recommendation="DEFER",
        rationale="The correction is not deterministic enough for automatic application.",
        confidence="low",
        options=[
            DecisionOption(key="APPLY_RECONCILED_CHANGE", label="Apply the staged change",
                           effect=DecisionEffect.APPLY_RECONCILED_CHANGE),
            DecisionOption(key="SKIP_CHANGE", label="Skip this change", effect=DecisionEffect.SKIP_CHANGE),
            DecisionOption(key="DEFER", label="Defer this change", effect=DecisionEffect.DEFER),
        ],
    )


def _initial_final_action(change: NoteChange) -> Action | None:
    if change.action in (Action.CREATE, Action.UPDATE, Action.NO_CHANGE):
        return change.action
    return None


def reconcile(inputs: ReconciliationInputs,
              selections: dict[str, str] | None = None) -> ReconciliationResult:
    """Reconcile every reviewed issue in stable proposal order."""
    selections = selections or {}
    reviewed_by_path = {item.change_path: item for item in inputs.agent_b_review.reviewed_changes}
    known_targets = _known_targets(inputs)
    reconciled_changes: list[ReconciledChange] = []
    decisions: list[HumanDecision] = []
    decision_number = 0

    for change_index, change in enumerate(inputs.reviewed_proposal.note_changes):
        change_id = f"RC-{change_index + 1:03d}"
        review = reviewed_by_path[change.target_path]
        existing = _existing_content(inputs, change.target_path)
        content = change.content
        reconciled_issues: list[ReconciledIssue] = []
        applied = []
        decision_ids: list[str] = []

        for local_index, agent_b_issue_index in enumerate(review.issue_indices, 1):
            source_issue = inputs.agent_b_review.issues[agent_b_issue_index]
            fix = classify_and_apply_fix(
                change,
                source_issue,
                content,
                existing,
                known_targets=known_targets,
            )
            issue_id = f"{change_id}-I{local_index:02d}"
            decision_id = None
            if fix.outcome is IssueOutcome.APPLIED:
                content = fix.content
                applied.extend(fix.patches)
            else:
                decision_number += 1
                decision_id = f"HR-{decision_number:03d}"
                decision_ids.append(decision_id)
            reconciled_issue = ReconciledIssue(
                id=issue_id,
                agent_b_issue_index=agent_b_issue_index,
                issue_type=source_issue.issue_type,
                explanation=source_issue.explanation,
                proposed_correction=source_issue.proposed_correction,
                evidence_refs=source_issue.evidence_refs,
                classification=fix.classification,
                outcome=fix.outcome,
                patches=fix.patches,
                human_decision_id=decision_id,
            )
            reconciled_issues.append(reconciled_issue)
            if decision_id is not None:
                decisions.append(_decision(decision_id, change_id, reconciled_issue, change))

        if change.action is Action.REVIEW_REQUIRED and not decision_ids:
            decision_number += 1
            decision_id = f"HR-{decision_number:03d}"
            synthetic = ReconciledIssue(
                id=f"{change_id}-I{len(reconciled_issues) + 1:02d}",
                agent_b_issue_index=-1,
                issue_type="existing_note",
                explanation=change.reason,
                proposed_correction="Resolve the original Agent A review requirement",
                classification="AMBIGUOUS",
                outcome="HUMAN_REQUIRED",
                human_decision_id=decision_id,
            )
            reconciled_issues.append(synthetic)
            decision_ids.append(decision_id)
            decisions.append(_decision(decision_id, change_id, synthetic, change))

        final_action = _initial_final_action(change)
        final_content = content if change.action is not Action.NO_CHANGE else None
        if decision_ids:
            status = ReconciledChangeStatus.BLOCKED
        elif applied:
            status = ReconciledChangeStatus.FIXED
        else:
            status = ReconciledChangeStatus.READY
        reconciled_changes.append(ReconciledChange(
            id=change_id,
            agent_a_change_index=change_index,
            original_action=change.action,
            original_target_path=change.target_path,
            original_content_sha256=_sha256_text(change.content),
            agent_b_status=review.status,
            agent_b_issue_indices=list(review.issue_indices),
            issues=reconciled_issues,
            applied_fixes=applied,
            human_decision_required=bool(decision_ids),
            human_decision_ids=decision_ids,
            final_action=final_action,
            final_target_path=change.target_path,
            final_content=final_content,
            final_content_sha256=_sha256_text(final_content) if final_content is not None else None,
            status=status,
        ))

    preliminary_findings = validate_final_changes(inputs, reconciled_changes)
    preservation_by_change: dict[str, list] = {}
    for finding in preliminary_findings:
        if finding.severity is not ValidationSeverity.WARNING or not finding.code.startswith("UPDATE_"):
            continue
        for change_id in finding.change_ids:
            preservation_by_change.setdefault(change_id, []).append(finding)
    change_by_id = {item.id: item for item in reconciled_changes}
    for change_id, findings in preservation_by_change.items():
        reconciled = change_by_id[change_id]
        if any(issue.issue_type.value in ("cumulative_integrity", "existing_note")
               and issue.human_decision_id for issue in reconciled.issues):
            continue
        decision_number += 1
        decision_id = f"HR-{decision_number:03d}"
        issue_id = f"{change_id}-I{len(reconciled.issues) + 1:02d}"
        explanation = " ".join(finding.message for finding in findings)
        synthetic = ReconciledIssue(
            id=issue_id,
            agent_b_issue_index=-1,
            issue_type="cumulative_integrity",
            explanation=explanation,
            proposed_correction="Confirm the content loss, skip the change, or defer it",
            classification=IssueClassification.AMBIGUOUS,
            outcome=IssueOutcome.HUMAN_REQUIRED,
            human_decision_id=decision_id,
        )
        reconciled.issues.append(synthetic)
        reconciled.human_decision_ids.append(decision_id)
        reconciled.human_decision_required = True
        reconciled.status = ReconciledChangeStatus.BLOCKED
        source = inputs.reviewed_proposal.note_changes[reconciled.agent_a_change_index]
        decisions.append(_decision(decision_id, change_id, synthetic, source))

    decision_by_id = {item.id: item for item in decisions}
    unknown = sorted(set(selections) - set(decision_by_id))
    if unknown:
        raise ValueError(f"Unknown decision IDs: {', '.join(unknown)}")
    selected_effects_by_change: dict[str, set[DecisionEffect]] = {}
    for decision_id, selected in selections.items():
        decision = decision_by_id[decision_id]
        option = next((item for item in decision.options if item.key == selected), None)
        if option is None:
            raise ValueError(f"Invalid option for {decision_id}: {selected}")
        for change_id in decision.change_ids:
            selected_effects_by_change.setdefault(change_id, set()).add(option.effect)
    conflicting = sorted(change_id for change_id, effects in selected_effects_by_change.items()
                         if len(effects) > 1)
    if conflicting:
        raise ValueError(f"Conflicting decision effects for changes: {', '.join(conflicting)}")

    for decision_id, selected in selections.items():
        decision = decision_by_id[decision_id]
        option = next(item for item in decision.options if item.key == selected)
        decision.selected_option = selected
        decision.status = (DecisionStatus.DEFERRED if option.effect is DecisionEffect.DEFER
                           else DecisionStatus.RESOLVED)
        for change_id in decision.change_ids:
            reconciled = change_by_id[change_id]
            for reconciled_issue in reconciled.issues:
                if reconciled_issue.id not in decision.issue_ids:
                    continue
                reconciled_issue.outcome = (
                    IssueOutcome.DEFERRED if option.effect is DecisionEffect.DEFER
                    else IssueOutcome.SKIPPED_WITH_HUMAN_APPROVAL
                )
            if option.effect is DecisionEffect.APPLY_RECONCILED_CHANGE:
                if reconciled.original_action is Action.REVIEW_REQUIRED:
                    target = inputs.vault / reconciled.original_target_path
                    reconciled.final_action = Action.UPDATE if target.is_file() else Action.CREATE
                else:
                    reconciled.final_action = reconciled.original_action
                if reconciled.final_action in (Action.CREATE, Action.UPDATE):
                    assert reconciled.final_content is not None
                    reconciled.final_content_sha256 = _sha256_text(reconciled.final_content)
            elif option.effect is DecisionEffect.SKIP_CHANGE:
                reconciled.final_action = Action.NO_CHANGE
                reconciled.final_content = None
                reconciled.final_content_sha256 = None
            else:
                reconciled.final_action = None
                reconciled.final_content = None
                reconciled.final_content_sha256 = None

    for reconciled in reconciled_changes:
        related = [item for item in decisions if reconciled.id in item.change_ids]
        pending = any(item.status is DecisionStatus.PENDING for item in related)
        reconciled.human_decision_required = pending
        if pending:
            reconciled.status = ReconciledChangeStatus.BLOCKED
        elif any(item.status is DecisionStatus.DEFERRED for item in related):
            reconciled.status = ReconciledChangeStatus.DEFERRED
        elif reconciled.final_action is Action.NO_CHANGE:
            reconciled.status = ReconciledChangeStatus.READY
        elif reconciled.applied_fixes:
            reconciled.status = ReconciledChangeStatus.FIXED
        else:
            reconciled.status = ReconciledChangeStatus.READY

    final_findings = validate_final_changes(inputs, reconciled_changes)
    for reconciled in reconciled_changes:
        reconciled.validation_findings = [item for item in final_findings if reconciled.id in item.change_ids]
        if any(item.severity is ValidationSeverity.ERROR for item in reconciled.validation_findings):
            reconciled.status = ReconciledChangeStatus.INVALID
    unresolved = [item.id for item in decisions if item.status is DecisionStatus.PENDING]
    has_errors = any(item.severity is ValidationSeverity.ERROR for item in final_findings)
    final = FinalChangeSet(
        source_run_id=inputs.run.name,
        reconciliation_version=RECONCILIATION_VERSION,
        provenance=inputs.provenance,
        input_sha256=inputs.input_sha256,
        pre_review_adjustments=inputs.pre_review_adjustments,
        changes=reconciled_changes,
        human_decisions=decisions,
        unresolved_decision_ids=unresolved,
        validation_findings=final_findings,
        state=(FinalChangeSetState.INVALID if has_errors
               else FinalChangeSetState.PENDING_HUMAN_REVIEW if unresolved
               else FinalChangeSetState.READY_FOR_WRITE),
    )
    return ReconciliationResult(final_change_set=final)
