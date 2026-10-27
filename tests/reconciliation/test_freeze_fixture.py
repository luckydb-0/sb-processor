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
    assert pending.final_change_set.human_decisions
    assert all(item.status is DecisionStatus.PENDING
               for item in pending.final_change_set.human_decisions)
    assert (pending_output / "HUMAN_REVIEW.md").is_file()

    changes_by_id = {item.id: item for item in pending.final_change_set.changes}
    selections: dict[str, str] = {}
    for decision in pending.final_change_set.human_decisions:
        change = changes_by_id[decision.change_ids[0]]
        source = inputs.reviewed_proposal.note_changes[change.agent_a_change_index]
        option_keys = {option.key for option in decision.options}
        if change.original_target_path == "Atlas/Dots/Machine Learning.md":
            selections[decision.id] = "DEFER"
        elif "REMOVE_LINK" in option_keys:
            selections[decision.id] = "REMOVE_LINK"
        elif (decision.category in {"link", "source_independent_wording"}
              or not source.content.strip()):
            selections[decision.id] = "DEFER"
        elif "ACKNOWLEDGE_CONTENT_LOSS" in option_keys:
            selections[decision.id] = "ACKNOWLEDGE_CONTENT_LOSS"
        elif "APPLY_RECONCILED_CHANGE" not in option_keys:
            selections[decision.id] = "DEFER"
        else:
            selections[decision.id] = "APPLY_RECONCILED_CHANGE"
    resolved = reconcile(inputs, selections)
    resolved_output = stage_reconciliation(run, resolved, inputs)

    assert resolved.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE
    assert resolved.final_change_set.unresolved_decision_ids == []
    assert any(item.status is DecisionStatus.DEFERRED
               for item in resolved.final_change_set.human_decisions)
    preview = (resolved_output / "WRITE_PREVIEW.md").read_text(encoding="utf-8")
    assert "## UPDATE" in preview
    resolved_clustering = by_path(resolved, "Atlas/Dots/Clustering.md")
    assert resolved_clustering.status is ReconciledChangeStatus.BLOCKED
    assert not (resolved_output / "diffs/RC-006.diff").exists()

    assert hashes(run) == run_before
    assert hashes(vault) == vault_before
