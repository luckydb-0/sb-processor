from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from sb_processor.reconciliation.artifacts import stage_reconciliation
from sb_processor.reconciliation.engine import reconcile
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    DecisionStatus,
    FinalChangeSetState,
    IssueClassification,
    IssueOutcome,
    ReconciledChangeStatus,
)


REPOSITORY = Path(__file__).resolve().parents[2]
RELEASE = REPOSITORY / "staging/agent_b_v1_freeze_benchmark/gpt-5.4-mini-low-freeze-release"
FIXTURE_VAULT = REPOSITORY / "staging/two_pass_fixture_vault"


def hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "reconciliation" not in path.parts
    }


def copied_release(tmp_path: Path) -> tuple[Path, Path]:
    if not RELEASE.is_dir() or not FIXTURE_VAULT.is_dir():
        pytest.skip("local Agent B freeze-release fixture is not available")
    run = tmp_path / "gpt-5.4-mini-low-freeze-release"
    vault = tmp_path / "two_pass_fixture_vault"
    shutil.copytree(RELEASE, run)
    shutil.copytree(FIXTURE_VAULT, vault)
    return run, vault


def by_path(result, path: str):
    return next(item for item in result.final_change_set.changes
                if item.original_target_path == path)


def test_freeze_release_reconciliation_lifecycle_is_auditable_and_does_not_write_vault(tmp_path: Path):
    run, vault = copied_release(tmp_path)
    run_before = hashes(run)
    vault_before = hashes(vault)
    inputs = load_reconciliation_inputs(run, vault)

    assert inputs.input_sha256["original_agent_a_proposal.json"] == (
        "ff9271de8855c47e442781884815bb059db68c941b236352e9bbca505131c64d"
    )
    assert inputs.input_sha256["proposal.json"] == (
        "4532fb1cb0ebdaaea20885a3b05559935aebe7569c97ace7d08bc9c79559036f"
    )
    assert any(item.field == "note_changes[22].target_path" for item in inputs.pre_review_adjustments)

    pending = reconcile(inputs)
    pending_output = stage_reconciliation(run, pending, inputs)

    lecture = by_path(
        pending,
        "Atlas/Sources/University/Machine Learning/Lectures/Machine Learning - 01 - Introduction.md",
    )
    original_lecture = inputs.reviewed_proposal.note_changes[lecture.agent_a_change_index]
    assert lecture.final_content == original_lecture.content
    assert lecture.applied_fixes == []

    clustering = by_path(pending, "Atlas/Dots/Clustering.md")
    assert clustering.issues[0].classification is IssueClassification.OBJECTIVE
    assert clustering.issues[0].outcome is IssueOutcome.APPLIED
    assert "**Source:**" not in clustering.final_content
    assert "**Pages/slides:**" in clustering.final_content

    regression = by_path(pending, "Atlas/Dots/Regression.md")
    semantic = next(item for item in regression.issues
                    if item.classification is IssueClassification.SEMANTIC_EXACT)
    assert semantic.outcome is IssueOutcome.APPLIED
    assert "and data mining" not in regression.final_content

    assert pending.final_change_set.state is FinalChangeSetState.PENDING_HUMAN_REVIEW
    assert len(pending.final_change_set.human_decisions) == 19
    assert sum(
        item.category == "UNRESOLVED_DEPENDENCY"
        for item in pending.final_change_set.human_decisions
    ) == 4
    assert all(item.status is DecisionStatus.PENDING
               for item in pending.final_change_set.human_decisions)
    assert (pending_output / "HUMAN_REVIEW.md").is_file()

    data_map_dependencies = [
        item for item in pending.final_change_set.dependencies
        if item.normalized_target == "data mining map"
    ]
    assert len(data_map_dependencies) == 16
    assert all(item.root_decision_id is None for item in data_map_dependencies)
    assert not any(
        "[[Data Mining - Map]]" in item.question
        for item in pending.final_change_set.human_decisions
    )

    identity = next(
        item for item in pending.final_change_set.human_decisions
        if item.category == "CONCEPT_IDENTITY"
    )
    assert {"RC-008", "RC-021"}.issubset(identity.change_ids)
    assert [item.key for item in identity.options] == ["KEEP_SEPARATE", "DEFER"]
    assert any(
        item.normalized_identity == "classification" and item.blocking
        for item in pending.final_change_set.identity_collisions
    )

    dataset_decision = next(
        item for item in pending.final_change_set.human_decisions
        if item.category == "CONTENT_PRESERVATION" and item.change_ids == ["RC-005"]
    )
    assert "APPLY_RECONCILED_CHANGE" not in {
        item.key for item in dataset_decision.options
    }
    with pytest.raises(ValueError, match=f"Invalid option for {dataset_decision.id}"):
        reconcile(inputs, {dataset_decision.id: "APPLY_RECONCILED_CHANGE"})
    business_analytics_decisions = [
        item for item in pending.final_change_set.human_decisions
        if "RC-022" in item.change_ids
    ]
    assert business_analytics_decisions
    assert all(
        not ({"APPLY_RECONCILED_CHANGE", "ACCEPT_STAGED_RISK"}
             & {option.key for option in item.options})
        for item in business_analytics_decisions
    )

    changes_by_id = {item.id: item for item in pending.final_change_set.changes}
    direct_ids = {
        decision.id: {
            issue_id.split("-I", 1)[0] for issue_id in decision.issue_ids
        }
        for decision in pending.final_change_set.human_decisions
    }
    issue_types = {
        decision.id: {
            issue.issue_type.value
            for change in pending.final_change_set.changes
            for issue in change.issues
            if issue.id in decision.issue_ids
        }
        for decision in pending.final_change_set.human_decisions
    }
    deferred_change_ids: set[str] = set()
    for decision in pending.final_change_set.human_decisions:
        for change_id in direct_ids[decision.id]:
            source = inputs.reviewed_proposal.note_changes[
                changes_by_id[change_id].agent_a_change_index
            ]
            if (issue_types[decision.id]
                    & {"source_independent_wording", "source_specific_result"}
                    or (not source.content.strip()
                        and decision.category != "CONCEPT_IDENTITY")):
                deferred_change_ids.add(change_id)
    selections: dict[str, str] = {}
    for decision in pending.final_change_set.human_decisions:
        option_keys = {option.key for option in decision.options}
        if "REMOVE_LINK" in option_keys:
            selections[decision.id] = "REMOVE_LINK"
        elif direct_ids[decision.id] & deferred_change_ids:
            selections[decision.id] = "DEFER"
        elif "KEEP_SEPARATE" in option_keys:
            selections[decision.id] = "KEEP_SEPARATE"
        elif "ACKNOWLEDGE_CONTENT_LOSS" in option_keys:
            selections[decision.id] = "ACKNOWLEDGE_CONTENT_LOSS"
        elif "ACCEPT_STAGED_RISK" in option_keys:
            selections[decision.id] = "ACCEPT_STAGED_RISK"
        elif "APPLY_RECONCILED_CHANGE" in option_keys:
            selections[decision.id] = "APPLY_RECONCILED_CHANGE"
        else:
            selections[decision.id] = "DEFER"
    resolved = reconcile(inputs, selections)
    resolved_output = stage_reconciliation(run, resolved, inputs)

    assert resolved.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE
    assert resolved.final_change_set.unresolved_decision_ids == []
    assert any(item.status is DecisionStatus.DEFERRED
               for item in resolved.final_change_set.human_decisions)
    assert not [
        item for item in resolved.final_change_set.identity_collisions if item.blocking
    ]
    assert resolved.final_change_set.applicable_change_ids == []
    assert by_path(
        resolved, "Atlas/Dots/Predictive Classification.md"
    ).status is ReconciledChangeStatus.BLOCKED
    assert len(resolved.final_change_set.accepted_risks) == 5
    assert any(
        item.decision_id == dataset_decision.id
        for item in resolved.final_change_set.accepted_risks
    )
    resolved_data_map_dependencies = [
        item for item in resolved.final_change_set.dependencies
        if item.normalized_target == "data mining map"
    ]
    assert resolved_data_map_dependencies
    assert all(item.target_state.value == "TARGET_DEFERRED"
               for item in resolved_data_map_dependencies)
    preview = (resolved_output / "WRITE_PREVIEW.md").read_text(encoding="utf-8")
    assert "## UPDATE" in preview
    resolved_clustering = by_path(resolved, "Atlas/Dots/Clustering.md")
    assert resolved_clustering.status is ReconciledChangeStatus.BLOCKED
    assert not (resolved_output / "diffs/RC-006.diff").exists()

    assert hashes(run) == run_before
    assert hashes(vault) == vault_before
