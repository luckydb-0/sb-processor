from __future__ import annotations

import hashlib
from pathlib import Path

from sb_processor.reconciliation.engine import reconcile
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    DecisionStatus,
    FinalChangeSetState,
    IssueClassification,
    IssueOutcome,
    ReconciledChangeStatus,
)

from .helpers import change, proposal, review, review_issue, reviewed_change, write_note, write_run


def loaded_inputs(tmp_path: Path, changes: list[dict], reviewed: list[dict], issues: list[dict] | None = None,
                  vault_contents: dict[str, str] | None = None):
    run = tmp_path / "run_1"
    write_run(run, proposal(changes), review(reviewed, issues=issues,
                                             overall_status="FIX" if issues else "PASS"))
    vault = tmp_path / "vault"
    vault.mkdir()
    for path, content in (vault_contents or {}).items():
        write_note(vault, path, content)
    return load_reconciliation_inputs(run, vault)


def test_pass_preserves_agent_a_action_path_and_content_byte_for_byte(tmp_path: Path):
    content = "---\ntype: concept\n---\n# Topic\nSupported body with intentional spacing.  \n"
    inputs = loaded_inputs(tmp_path, [change(content=content)], [reviewed_change("Dots/Topic.md")])

    result = reconcile(inputs)

    reconciled = result.final_change_set.changes[0]
    assert reconciled.id == "RC-001"
    assert reconciled.final_action.value == "CREATE"
    assert reconciled.final_target_path == "Dots/Topic.md"
    assert reconciled.final_content == content
    assert reconciled.final_content_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert reconciled.status is ReconciledChangeStatus.READY
    assert reconciled.issues == []


def test_fix_applies_objective_and_exact_semantic_patches_in_issue_order(tmp_path: Path):
    content = (
        "---\ntype: concept\nsource_file: lecture.pdf\nlocation: /tmp/lecture.pdf\n---\n"
        "# Regression\nRegression is a task in machine learning and data mining.\n\n"
        "## Sources\n### [[Lecture 01]]\n**Source:** `lecture.pdf`  \n"
        "**Location:** /tmp/lecture.pdf  \n**Pages/slides:** 4\n"
    )
    issues = [
        review_issue("Dots/Topic.md", "provenance",
                     "Keep the Lecture Note wikilink and page reference; remove direct PDF source_file/location metadata",
                     explanation="Concept Note duplicates direct PDF metadata"),
        review_issue("Dots/Topic.md", "source_fidelity",
                     'Remove "and data mining" from the body'),
    ]
    inputs = loaded_inputs(
        tmp_path,
        [change(content=content)],
        [reviewed_change("Dots/Topic.md", status="FIX", issue_indices=[0, 1])],
        issues,
    )

    result = reconcile(inputs)

    reconciled = result.final_change_set.changes[0]
    assert [item.id for item in reconciled.issues] == ["RC-001-I01", "RC-001-I02"]
    assert [item.classification for item in reconciled.issues] == [
        IssueClassification.OBJECTIVE,
        IssueClassification.SEMANTIC_EXACT,
    ]
    assert all(item.outcome is IssueOutcome.APPLIED for item in reconciled.issues)
    assert "source_file:" not in reconciled.final_content
    assert "and data mining" not in reconciled.final_content
    assert "**Pages/slides:** 4" in reconciled.final_content
    assert reconciled.status is ReconciledChangeStatus.FIXED
    assert len(reconciled.applied_fixes) == 5


def test_multiple_issues_keep_independent_outcomes_and_block_only_for_ambiguous_fix(tmp_path: Path):
    content = (
        "---\ntype: concept\nsource_file: lecture.pdf\n---\n# Topic\n"
        "See [[Statistics]].\n## Sources\n### [[Lecture 01]]\n**Pages/slides:** 3\n"
    )
    issues = [
        review_issue("Dots/Topic.md", "provenance",
                     "Keep the Lecture Note wikilink and page reference; remove direct PDF source_file/location metadata",
                     explanation="Concept Note duplicates direct PDF metadata"),
        review_issue("Dots/Topic.md", "link", "Use a verified canonical target or remove the link",
                     explanation="Unresolved wikilink: [[Statistics]]"),
    ]
    inputs = loaded_inputs(
        tmp_path,
        [change(content=content)],
        [reviewed_change("Dots/Topic.md", status="FIX", issue_indices=[0, 1])],
        issues,
    )

    result = reconcile(inputs)

    reconciled = result.final_change_set.changes[0]
    assert [item.outcome for item in reconciled.issues] == [
        IssueOutcome.APPLIED,
        IssueOutcome.HUMAN_REQUIRED,
    ]
    assert reconciled.status is ReconciledChangeStatus.BLOCKED
    assert reconciled.human_decision_required is True
    assert reconciled.human_decision_ids == ["HR-001"]
    assert result.final_change_set.human_decisions[0].issue_ids == ["RC-001-I02"]


def unresolved_link_inputs(tmp_path: Path, *, action: str = "CREATE", vault_contents=None):
    content = "---\ntype: concept\n---\n# Topic\nSee [[Statistics]].\n"
    issues = [review_issue("Dots/Topic.md", "link", "Use a verified canonical target or remove the link",
                           explanation="Unresolved wikilink: [[Statistics]]")]
    return loaded_inputs(
        tmp_path,
        [change(content=content, action=action)],
        [reviewed_change("Dots/Topic.md", status="FIX", issue_indices=[0])],
        issues,
        vault_contents=vault_contents,
    )


def test_pending_decision_is_narrow_stable_and_blocks_final_state(tmp_path: Path):
    result = reconcile(unresolved_link_inputs(tmp_path))

    decision = result.final_change_set.human_decisions[0]
    assert decision.id == "HR-001"
    assert decision.status is DecisionStatus.PENDING
    assert decision.question == "Should `Dots/Topic.md` keep the unresolved wikilink `[[Statistics]]`?"
    assert [option.key for option in decision.options] == [
        "APPLY_RECONCILED_CHANGE", "SKIP_CHANGE", "DEFER"
    ]
    assert result.final_change_set.unresolved_decision_ids == ["HR-001"]
    assert result.final_change_set.state is FinalChangeSetState.PENDING_HUMAN_REVIEW


def test_resolved_decision_can_apply_reconciled_content_without_llm_reinterpretation(tmp_path: Path):
    inputs = unresolved_link_inputs(tmp_path)

    result = reconcile(inputs, {"HR-001": "APPLY_RECONCILED_CHANGE"})

    decision = result.final_change_set.human_decisions[0]
    reconciled = result.final_change_set.changes[0]
    assert decision.status is DecisionStatus.RESOLVED
    assert decision.selected_option == "APPLY_RECONCILED_CHANGE"
    assert reconciled.issues[0].outcome is IssueOutcome.SKIPPED_WITH_HUMAN_APPROVAL
    assert reconciled.final_action.value == "CREATE"
    assert "[[Statistics]]" in reconciled.final_content
    assert reconciled.human_decision_required is False
    assert result.final_change_set.unresolved_decision_ids == []


def test_resolved_decision_can_skip_change(tmp_path: Path):
    result = reconcile(unresolved_link_inputs(tmp_path), {"HR-001": "SKIP_CHANGE"})

    decision = result.final_change_set.human_decisions[0]
    reconciled = result.final_change_set.changes[0]
    assert decision.status is DecisionStatus.RESOLVED
    assert reconciled.final_action.value == "NO_CHANGE"
    assert reconciled.final_content is None
    assert reconciled.status is ReconciledChangeStatus.READY


def test_deferred_decision_remains_explicit_but_is_not_pending(tmp_path: Path):
    result = reconcile(unresolved_link_inputs(tmp_path), {"HR-001": "DEFER"})

    decision = result.final_change_set.human_decisions[0]
    reconciled = result.final_change_set.changes[0]
    assert decision.status is DecisionStatus.DEFERRED
    assert decision.selected_option == "DEFER"
    assert reconciled.final_action is None
    assert reconciled.status is ReconciledChangeStatus.DEFERRED
    assert reconciled.issues[0].outcome is IssueOutcome.DEFERRED
    assert result.final_change_set.unresolved_decision_ids == []


def test_review_required_resolution_infers_update_only_when_target_exists(tmp_path: Path):
    content = "---\ntype: concept\n---\n# Topic\nProposed update.\n"
    inputs = loaded_inputs(
        tmp_path,
        [change(content=content, action="REVIEW_REQUIRED")],
        [reviewed_change("Dots/Topic.md", status="REVIEW_REQUIRED")],
        vault_contents={"Dots/Topic.md": "---\ntype: concept\n---\n# Topic\nExisting.\n"},
    )

    pending = reconcile(inputs)
    resolved = reconcile(inputs, {"HR-001": "APPLY_RECONCILED_CHANGE"})

    assert pending.final_change_set.changes[0].final_action is None
    assert resolved.final_change_set.changes[0].final_action.value == "UPDATE"
    assert resolved.final_change_set.changes[0].final_content == content


def test_resolved_review_required_infers_create_when_target_is_absent(tmp_path: Path):
    inputs = loaded_inputs(
        tmp_path,
        [change(action="REVIEW_REQUIRED")],
        [reviewed_change("Dots/Topic.md", status="REVIEW_REQUIRED")],
    )

    result = reconcile(inputs, {"HR-001": "APPLY_RECONCILED_CHANGE"})

    assert result.final_change_set.changes[0].final_action.value == "CREATE"


def test_decision_resolution_rejects_unknown_ids_and_options(tmp_path: Path):
    inputs = unresolved_link_inputs(tmp_path)

    try:
        reconcile(inputs, {"HR-999": "DEFER"})
    except ValueError as error:
        assert "Unknown decision IDs" in str(error)
    else:
        raise AssertionError("unknown decision ID should fail")

    try:
        reconcile(inputs, {"HR-001": "INVENTED"})
    except ValueError as error:
        assert "Invalid option for HR-001" in str(error)
    else:
        raise AssertionError("unknown decision option should fail")
