from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..models import Action, NoteChange, ReviewStatus
from .dependencies import analyze_dependencies
from .fixes import classify_and_apply_fix
from .identities import (
    build_effective_identity_registry,
    plan_keep_separate,
    IdentityResolutionPlan,
)
from .inputs import ReconciliationInputs, resolve_vault_target
from .models import (
    DecisionEffect,
    DecisionCategory,
    DecisionOption,
    DecisionStatus,
    FinalChangeSet,
    FinalChangeSetState,
    HumanDecision,
    IssueOutcome,
    IssueClassification,
    IssueResolutionDisposition,
    ReconciledChange,
    ReconciledChangeStatus,
    ReconciledIssue,
    ReconciliationResult,
    PatchKind,
    PatchOperation,
    ValidationSeverity,
)
from .validators import validate_final_changes


RECONCILIATION_VERSION = "reconciliation-v1.1"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _existing_content(inputs: ReconciliationInputs, path: str) -> str | None:
    target = resolve_vault_target(inputs.vault, path)
    return target.read_text(encoding="utf-8") if target is not None and target.is_file() else None


def _known_targets(inputs: ReconciliationInputs) -> set[str]:
    paths = {note.path.removesuffix(".md") for note in inputs.vault_notes}
    paths.update(change.target_path.removesuffix(".md") for change in inputs.reviewed_proposal.note_changes)
    return paths


def _unresolved_link_tokens(explanation: str) -> list[str]:
    return list(dict.fromkeys(re.findall(
        r"Unresolved wikilink: (\[\[[^\]]+\]\])",
        explanation,
    )))


def _decision(decision_id: str, change_id: str, issue: ReconciledIssue,
              change: NoteChange) -> HumanDecision:
    unresolved_links = _unresolved_link_tokens(issue.explanation)
    unresolved_link = unresolved_links[0] if len(unresolved_links) == 1 else None
    if unresolved_link:
        question = f"Should `{change.target_path}` keep the unresolved wikilink `{unresolved_link}`?"
    elif issue.issue_type.value == "alias":
        question = f"Should `{change.target_path}` keep the alias questioned by Agent B?"
    elif issue.issue_type.value in ("concept_boundary", "existing_note"):
        question = f"Should `{change.target_path}` be applied as the separate change Agent A proposed?"
    elif issue.issue_type.value == "cumulative_integrity":
        question = f"Should `{change.target_path}` proceed even though it does not preserve all existing useful content?"
    else:
        question = f"Should `{change.target_path}` proceed with this unresolved {issue.issue_type.value} issue?"
    options = [
        DecisionOption(key="APPLY_RECONCILED_CHANGE", label="Apply the staged change",
                       effect=DecisionEffect.APPLY_RECONCILED_CHANGE),
    ]
    if unresolved_link and unresolved_link in change.content:
        options.append(DecisionOption(
            key="REMOVE_LINK",
            label="Remove only the wikilink markup",
            effect=DecisionEffect.REMOVE_LINK,
        ))
    options.extend([
        DecisionOption(key="SKIP_CHANGE", label="Skip this change", effect=DecisionEffect.SKIP_CHANGE),
        DecisionOption(key="DEFER", label="Defer this change", effect=DecisionEffect.DEFER),
    ])
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
        options=options,
    )


def _remove_unresolved_link(reconciled: ReconciledChange, issue: ReconciledIssue) -> None:
    tokens = _unresolved_link_tokens(issue.explanation)
    if len(tokens) != 1 or reconciled.final_content is None:
        raise ValueError(f"Decision {issue.human_decision_id} has no removable wikilink")
    token = tokens[0]
    positions = [match.start() for match in re.finditer(re.escape(token), reconciled.final_content)]
    if not positions:
        raise ValueError(
            f"Decision {issue.human_decision_id} wikilink is not removable: {token}"
        )
    inner = token[2:-2]
    visible = inner.split("|", 1)[1] if "|" in inner else inner.split("#", 1)[0]
    patches = [
        PatchOperation(
            kind=PatchKind.REPLACE,
            start=start,
            end=start + len(token),
            before=token,
            after=visible,
        )
        for start in positions
    ]
    reconciled.final_content = reconciled.final_content.replace(token, visible)
    reconciled.final_content_sha256 = _sha256_text(reconciled.final_content)
    reconciled.applied_fixes.extend(patches)
    issue.patches.extend(patches)
    issue.outcome = IssueOutcome.APPLIED


def _initial_final_action(change: NoteChange, inputs: ReconciliationInputs) -> Action | None:
    if change.action in (Action.CREATE, Action.UPDATE, Action.NO_CHANGE):
        return change.action
    if change.action is Action.REVIEW_REQUIRED:
        target = resolve_vault_target(inputs.vault, change.target_path)
        return Action.UPDATE if target is not None and target.is_file() else Action.CREATE
    return None


def _direct_change_ids(decision: HumanDecision) -> list[str]:
    direct = {
        issue_id.split("-I", 1)[0]
        for issue_id in decision.issue_ids
        if "-I" in issue_id
    }
    return sorted(direct or set(decision.change_ids))


def _next_decision_id(decisions: list[HumanDecision]) -> str:
    number = max((int(item.id.removeprefix("HR-")) for item in decisions), default=0) + 1
    return f"HR-{number:03d}"


def _drop_decisions(decisions: list[HumanDecision], decision_ids: set[str]) -> None:
    decisions[:] = [item for item in decisions if item.id not in decision_ids]


def _replace_issue_decisions(changes: list[ReconciledChange], old_ids: set[str],
                             root_id: str) -> list[str]:
    issue_ids: list[str] = []
    for change in changes:
        replaced = False
        for issue in change.issues:
            if issue.human_decision_id not in old_ids:
                continue
            issue.human_decision_id = root_id
            issue_ids.append(issue.id)
            replaced = True
        if replaced:
            change.human_decision_ids = [
                item for item in change.human_decision_ids if item not in old_ids
            ]
            if root_id not in change.human_decision_ids:
                change.human_decision_ids.append(root_id)
    return issue_ids


def _group_identity_decisions(
        inputs: ReconciliationInputs,
        changes: list[ReconciledChange],
        decisions: list[HumanDecision],
        dependencies,
        identity_analysis,
) -> dict[str, IdentityResolutionPlan]:
    plans: dict[str, IdentityResolutionPlan] = {}
    change_by_path = {
        (item.final_target_path or item.original_target_path): item
        for item in changes
    }
    for collision in identity_analysis.collisions:
        if not collision.blocking:
            continue
        participant_ids = set(collision.change_ids)
        for claim in collision.claims:
            if claim.canonical_path in change_by_path:
                participant_ids.add(change_by_path[claim.canonical_path].id)
        dependent_ids = {
            item.source_change_id
            for item in dependencies
            if item.normalized_target == collision.normalized_identity
        }
        relevant_ids = participant_ids | dependent_ids
        old_ids = {
            issue.human_decision_id
            for change in changes
            if change.id in participant_ids
            for issue in change.issues
            if (issue.issue_type.value in ("existing_note", "concept_boundary", "alias")
                and issue.human_decision_id is not None)
        }
        root_id = sorted(old_ids)[0] if old_ids else _next_decision_id(decisions)
        issue_ids = _replace_issue_decisions(changes, old_ids, root_id)
        if not issue_ids:
            direct_change = next(item for item in changes if item.id in participant_ids)
            synthetic = ReconciledIssue(
                id=f"{direct_change.id}-I{len(direct_change.issues) + 1:02d}",
                agent_b_issue_index=-1,
                issue_type="concept_boundary",
                explanation=(
                    f"Identity `{collision.normalized_identity}` maps to more than one note."
                ),
                proposed_correction="Resolve the mechanical identity collision",
                classification=IssueClassification.AMBIGUOUS,
                outcome=IssueOutcome.HUMAN_REQUIRED,
                human_decision_id=root_id,
            )
            direct_change.issues.append(synthetic)
            direct_change.human_decision_ids.append(root_id)
            issue_ids.append(synthetic.id)
        _drop_decisions(decisions, old_ids)
        plan = plan_keep_separate(inputs, collision, changes)
        options: list[DecisionOption] = []
        if plan is not None:
            plans[root_id] = plan
            options.append(DecisionOption(
                key="KEEP_SEPARATE",
                label="Keep both identities separate",
                effect=DecisionEffect.KEEP_SEPARATE,
                consequence=(
                    "Create the proposed canonical note and remove only the exact colliding "
                    f"alias from `{plan.existing_path}`, then revalidate identities and links."
                ),
            ))
        options.append(DecisionOption(
            key="DEFER",
            label="Defer the identity change",
            effect=DecisionEffect.DEFER,
            consequence=(
                "Exclude the proposed identity changes and recompute dependents against the "
                "unchanged vault."
            ),
        ))
        decision = HumanDecision(
            id=root_id,
            change_ids=sorted(relevant_ids),
            issue_ids=sorted(set(issue_ids)),
            category=DecisionCategory.CONCEPT_IDENTITY.value,
            status=DecisionStatus.PENDING,
            question=(
                f"Should `{collision.normalized_identity}` remain a separate canonical identity?"
            ),
            context=(
                "The effective vault registry maps this title/alias identity to multiple notes: "
                + ", ".join(sorted({item.canonical_path for item in collision.claims}))
            ),
            agent_a_position="Create or retain the proposed separate identity.",
            agent_b_position="Resolve the title/alias boundary before writing.",
            recommendation="DEFER",
            rationale="Semantic equivalence is not proven by an alias collision.",
            confidence="low",
            options=options,
            blocking=True,
        )
        decisions.append(decision)
        collision.human_decision_id = root_id
        collision.change_ids = sorted(participant_ids)
        collision.dependent_change_ids = sorted(dependent_ids - participant_ids)
        for change in changes:
            if change.id in relevant_ids:
                if root_id not in change.human_decision_ids:
                    change.human_decision_ids.append(root_id)
                change.human_decision_required = True
                change.status = ReconciledChangeStatus.BLOCKED
        for dependency in dependencies:
            if dependency.normalized_target == collision.normalized_identity:
                dependency.root_decision_id = root_id
    decisions.sort(key=lambda item: int(item.id.removeprefix("HR-")))
    return plans


def _reconcile_dependency_decisions(
        changes: list[ReconciledChange],
        decisions: list[HumanDecision],
        dependencies,
) -> None:
    decision_by_id = {item.id: item for item in decisions}
    change_by_id = {item.id: item for item in changes}
    for dependency in dependencies:
        source = change_by_id[dependency.source_change_id]
        matching_issues = [
            issue for issue in source.issues
            if dependency.token in _unresolved_link_tokens(issue.explanation)
        ]
        old_ids = {
            issue.human_decision_id for issue in matching_issues
            if issue.human_decision_id is not None
        }
        if not dependency.blocking:
            _drop_decisions(decisions, old_ids)
            source.human_decision_ids = [
                item for item in source.human_decision_ids if item not in old_ids
            ]
            for issue in matching_issues:
                issue.human_decision_id = None
                issue.outcome = IssueOutcome.APPLIED
                issue.resolution = IssueResolutionDisposition.ISSUE_FIXED
            continue
        if dependency.root_decision_id is None:
            continue
        root = decision_by_id.get(dependency.root_decision_id)
        if root is None:
            continue
        _drop_decisions(decisions, old_ids - {root.id})
        source.human_decision_ids = [
            item for item in source.human_decision_ids
            if item not in old_ids or item == root.id
        ]
        if root.id not in source.human_decision_ids:
            source.human_decision_ids.append(root.id)
        if source.id not in root.change_ids:
            root.change_ids.append(source.id)
            root.change_ids.sort()
        if not matching_issues:
            synthetic = ReconciledIssue(
                id=f"{source.id}-I{len(source.issues) + 1:02d}",
                agent_b_issue_index=-1,
                issue_type="link",
                explanation=f"Unresolved wikilink: {dependency.token}",
                proposed_correction="Resolve the target's root decision",
                classification=IssueClassification.AMBIGUOUS,
                outcome=IssueOutcome.HUMAN_REQUIRED,
                human_decision_id=root.id,
            )
            source.issues.append(synthetic)
            matching_issues = [synthetic]
        for issue in matching_issues:
            issue.human_decision_id = root.id
        source.human_decision_required = True
        source.status = ReconciledChangeStatus.BLOCKED
    decisions.sort(key=lambda item: int(item.id.removeprefix("HR-")))


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

        if (change.action is Action.REVIEW_REQUIRED or review.status is ReviewStatus.REVIEW_REQUIRED) \
                and not decision_ids:
            decision_number += 1
            decision_id = f"HR-{decision_number:03d}"
            explanation = (
                change.reason
                if change.action is Action.REVIEW_REQUIRED
                else "Agent B marked the whole change REVIEW_REQUIRED after its issue-level review."
            )
            synthetic = ReconciledIssue(
                id=f"{change_id}-I{len(reconciled_issues) + 1:02d}",
                agent_b_issue_index=-1,
                issue_type="existing_note",
                explanation=explanation,
                proposed_correction="Resolve the explicit whole-change review requirement",
                classification="AMBIGUOUS",
                outcome="HUMAN_REQUIRED",
                human_decision_id=decision_id,
            )
            reconciled_issues.append(synthetic)
            decision_ids.append(decision_id)
            decisions.append(_decision(decision_id, change_id, synthetic, change))

        final_action = _initial_final_action(change, inputs)
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
            expected_existing_content_sha256=change.original_content_hash,
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

    initial_identities = build_effective_identity_registry(inputs, reconciled_changes)
    initial_dependencies = analyze_dependencies(
        inputs, reconciled_changes, initial_identities
    )
    identity_plans = _group_identity_decisions(
        inputs,
        reconciled_changes,
        decisions,
        initial_dependencies,
        initial_identities,
    )
    _reconcile_dependency_decisions(
        reconciled_changes, decisions, initial_dependencies
    )

    decision_by_id = {item.id: item for item in decisions}
    unknown = sorted(set(selections) - set(decision_by_id))
    if unknown:
        raise ValueError(f"Unknown decision IDs: {', '.join(unknown)}")
    selected_effects_by_change: dict[str, set[DecisionEffect]] = {}
    selection_options: dict[str, DecisionOption] = {}
    for decision_id, selected in selections.items():
        decision = decision_by_id[decision_id]
        option = next((item for item in decision.options if item.key == selected), None)
        if option is None:
            raise ValueError(f"Invalid option for {decision_id}: {selected}")
        selection_options[decision_id] = option
        if option.effect is not DecisionEffect.REMOVE_LINK:
            for change_id in _direct_change_ids(decision):
                selected_effects_by_change.setdefault(change_id, set()).add(option.effect)
    conflicting = sorted(change_id for change_id, effects in selected_effects_by_change.items()
                         if len(effects) > 1)
    if conflicting:
        raise ValueError(f"Conflicting decision effects for changes: {', '.join(conflicting)}")

    ordered_selections = sorted(
        selections.items(),
        key=lambda item: selection_options[item[0]].effect is not DecisionEffect.REMOVE_LINK,
    )
    for decision_id, selected in ordered_selections:
        decision = decision_by_id[decision_id]
        option = selection_options[decision_id]
        decision.selected_option = selected
        decision.status = (DecisionStatus.DEFERRED if option.effect is DecisionEffect.DEFER
                           else DecisionStatus.RESOLVED)
        for change_id in _direct_change_ids(decision):
            reconciled = change_by_id[change_id]
            for reconciled_issue in reconciled.issues:
                if reconciled_issue.id not in decision.issue_ids:
                    continue
                if option.effect is DecisionEffect.REMOVE_LINK:
                    _remove_unresolved_link(reconciled, reconciled_issue)
                else:
                    reconciled_issue.outcome = (
                        IssueOutcome.DEFERRED if option.effect is DecisionEffect.DEFER
                        else IssueOutcome.SKIPPED_WITH_HUMAN_APPROVAL
                    )
            if option.effect is DecisionEffect.APPLY_RECONCILED_CHANGE:
                if reconciled.original_action is Action.REVIEW_REQUIRED:
                    target = resolve_vault_target(inputs.vault, reconciled.original_target_path)
                    reconciled.final_action = (
                        Action.UPDATE if target is not None and target.is_file() else Action.CREATE
                    )
                else:
                    reconciled.final_action = reconciled.original_action
                if reconciled.final_action in (Action.CREATE, Action.UPDATE):
                    assert reconciled.final_content is not None
                    reconciled.final_content_sha256 = _sha256_text(reconciled.final_content)
            elif option.effect is DecisionEffect.KEEP_SEPARATE:
                plan = identity_plans.get(decision_id)
                if plan is None:
                    raise ValueError(
                        f"Decision {decision_id} has no safe KEEP_SEPARATE transformation"
                    )
                create = change_by_id[plan.create_change_id]
                existing = change_by_id[plan.existing_change_id]
                create.final_action = Action.CREATE
                assert create.final_content is not None
                create.final_content_sha256 = _sha256_text(create.final_content)
                existing.final_action = Action.UPDATE
                existing.final_content = plan.final_content
                existing.final_content_sha256 = _sha256_text(plan.final_content)
                if plan.patch not in existing.applied_fixes:
                    existing.applied_fixes.append(plan.patch)
                for affected in (create, existing):
                    for affected_issue in affected.issues:
                        if affected_issue.id in decision.issue_ids:
                            affected_issue.outcome = IssueOutcome.APPLIED
                            affected_issue.resolution = (
                                IssueResolutionDisposition.ISSUE_FIXED
                            )
            elif option.effect is DecisionEffect.REMOVE_LINK:
                pass
            elif option.effect is DecisionEffect.SKIP_CHANGE:
                reconciled.final_action = Action.NO_CHANGE
                reconciled.final_content = None
                reconciled.final_content_sha256 = None
            else:
                reconciled.final_action = None
                reconciled.final_content = None
                reconciled.final_content_sha256 = None

    direct_decisions_by_change: dict[str, list[HumanDecision]] = {}
    for decision in decisions:
        for change_id in _direct_change_ids(decision):
            direct_decisions_by_change.setdefault(change_id, []).append(decision)

    for reconciled in reconciled_changes:
        related = [item for item in decisions if reconciled.id in item.change_ids]
        direct_related = direct_decisions_by_change.get(reconciled.id, [])
        pending = any(item.status is DecisionStatus.PENDING for item in related)
        reconciled.human_decision_required = pending
        if pending:
            reconciled.status = ReconciledChangeStatus.BLOCKED
        elif any(item.status is DecisionStatus.DEFERRED for item in direct_related):
            reconciled.status = ReconciledChangeStatus.DEFERRED
        elif reconciled.final_action is Action.NO_CHANGE:
            reconciled.status = ReconciledChangeStatus.READY
        elif reconciled.applied_fixes:
            reconciled.status = ReconciledChangeStatus.FIXED
        else:
            reconciled.status = ReconciledChangeStatus.READY

    final_identities = build_effective_identity_registry(inputs, reconciled_changes)
    final_dependencies = analyze_dependencies(inputs, reconciled_changes, final_identities)
    for reconciled in reconciled_changes:
        reconciled.dependencies = [
            item for item in final_dependencies
            if item.source_change_id == reconciled.id
        ]
        if (reconciled.status not in (
                ReconciledChangeStatus.DEFERRED,
                ReconciledChangeStatus.SKIPPED,
                ReconciledChangeStatus.INVALID,
            ) and any(item.blocking for item in reconciled.dependencies)):
            reconciled.status = ReconciledChangeStatus.BLOCKED

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
        dependencies=final_dependencies,
        identity_collisions=list(final_identities.collisions),
        applicable_change_ids=[
            item.id for item in reconciled_changes
            if item.status in (
                ReconciledChangeStatus.READY,
                ReconciledChangeStatus.FIXED,
            ) and item.final_action in (Action.CREATE, Action.UPDATE)
        ],
        state=(FinalChangeSetState.INVALID if has_errors
               else FinalChangeSetState.PENDING_HUMAN_REVIEW if unresolved
               else FinalChangeSetState.READY_FOR_WRITE),
    )
    return ReconciliationResult(final_change_set=final)
