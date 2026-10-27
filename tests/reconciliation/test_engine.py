from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb_processor.reconciliation.engine import reconcile
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    DecisionCategory,
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
    statuses = {item["status"] for item in reviewed}
    overall_status = ("REVIEW_REQUIRED" if "REVIEW_REQUIRED" in statuses
                      else "FIX" if "FIX" in statuses else "PASS")
    write_run(run, proposal(changes), review(
        reviewed, issues=issues, overall_status=overall_status
    ))
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
        vault_contents={"Sources/Lecture 01.md": "---\ntype: lecture\n---\n# Lecture 01\n"},
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


def test_agent_b_review_required_without_issues_still_requires_human_decision(tmp_path: Path):
    inputs = loaded_inputs(
        tmp_path,
        [change()],
        [reviewed_change("Dots/Topic.md", status="REVIEW_REQUIRED")],
    )

    result = reconcile(inputs)

    reconciled = result.final_change_set.changes[0]
    assert reconciled.status is ReconciledChangeStatus.BLOCKED
    assert reconciled.human_decision_ids == ["HR-001"]
    assert result.final_change_set.human_decisions[0].category == "existing_note"
    assert result.final_change_set.state is FinalChangeSetState.PENDING_HUMAN_REVIEW


def test_agent_b_review_required_with_only_auto_fixes_still_requires_human_decision(
        tmp_path: Path):
    content = (
        "---\ntype: concept\nsource_file: lecture.pdf\n---\n# Topic\n"
        "## Sources\n### [[Lecture 01]]\n**Pages/slides:** 3\n"
    )
    issues = [review_issue(
        "Dots/Topic.md",
        "provenance",
        "Keep the Lecture Note wikilink and page reference; remove direct PDF source_file/location metadata",
        explanation="Concept Note duplicates direct PDF metadata",
    )]
    inputs = loaded_inputs(
        tmp_path,
        [change(content=content)],
        [reviewed_change("Dots/Topic.md", status="REVIEW_REQUIRED", issue_indices=[0])],
        issues,
        vault_contents={"Sources/Lecture 01.md": "---\ntype: lecture\n---\n# Lecture 01\n"},
    )

    result = reconcile(inputs)

    reconciled = result.final_change_set.changes[0]
    assert reconciled.issues[0].outcome is IssueOutcome.APPLIED
    assert reconciled.human_decision_ids == ["HR-001"]
    assert reconciled.status is ReconciledChangeStatus.BLOCKED


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
        "APPLY_RECONCILED_CHANGE", "REMOVE_LINK", "SKIP_CHANGE", "DEFER"
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


def test_resolved_link_decision_can_remove_only_wikilink_markup(tmp_path: Path):
    result = reconcile(unresolved_link_inputs(tmp_path), {"HR-001": "REMOVE_LINK"})

    decision = result.final_change_set.human_decisions[0]
    reconciled = result.final_change_set.changes[0]
    assert decision.status is DecisionStatus.RESOLVED
    assert decision.selected_option == "REMOVE_LINK"
    assert reconciled.issues[0].outcome is IssueOutcome.APPLIED
    assert "See Statistics." in reconciled.final_content
    assert "[[Statistics]]" not in reconciled.final_content
    assert reconciled.applied_fixes[-1].before == "[[Statistics]]"
    assert reconciled.applied_fixes[-1].after == "Statistics"
    assert result.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE


def test_remove_link_replaces_every_occurrence_of_one_exact_unresolved_link(tmp_path: Path):
    inputs = unresolved_link_inputs(tmp_path)
    inputs.reviewed_proposal.note_changes[0].content = (
        "---\ntype: concept\n---\n# Topic\nSee [[Statistics]], then revisit [[Statistics]].\n"
    )

    result = reconcile(inputs, {"HR-001": "REMOVE_LINK"})

    reconciled = result.final_change_set.changes[0]
    assert reconciled.final_content.count("Statistics") == 2
    assert "[[Statistics]]" not in reconciled.final_content
    assert [patch.before for patch in reconciled.issues[0].patches] == [
        "[[Statistics]]", "[[Statistics]]"
    ]


def test_remove_link_is_not_offered_when_one_decision_names_different_links(tmp_path: Path):
    content = "---\ntype: concept\n---\n# Topic\nSee [[One]] and [[Two]].\n"
    issues = [review_issue(
        "Dots/Topic.md",
        "link",
        "Use verified canonical targets or remove the links",
        explanation="Unresolved wikilink: [[One]] Unresolved wikilink: [[Two]]",
    )]
    inputs = loaded_inputs(
        tmp_path,
        [change(content=content)],
        [reviewed_change("Dots/Topic.md", status="FIX", issue_indices=[0])],
        issues,
    )

    result = reconcile(inputs)

    assert "REMOVE_LINK" not in [
        option.key for option in result.final_change_set.human_decisions[0].options
    ]


def test_local_link_removal_is_ordered_before_a_whole_change_defer(tmp_path: Path):
    content = "---\ntype: concept\n---\n# Topic\nSee [[Statistics]].\n"
    issues = [
        review_issue(
            "Dots/Topic.md",
            "link",
            "Use a verified canonical target or remove the link",
            explanation="Unresolved wikilink: [[Statistics]]",
        ),
        review_issue(
            "Dots/Topic.md",
            "claim_strength",
            "Confirm or remove the claim",
            explanation="The claim is not fully supported by the supplied source.",
        ),
    ]
    inputs = loaded_inputs(
        tmp_path,
        [change(content=content)],
        [reviewed_change("Dots/Topic.md", status="FIX", issue_indices=[0, 1])],
        issues,
    )

    result = reconcile(inputs, {"HR-002": "DEFER", "HR-001": "REMOVE_LINK"})

    reconciled = result.final_change_set.changes[0]
    assert reconciled.status is ReconciledChangeStatus.DEFERRED
    assert reconciled.issues[0].outcome is IssueOutcome.APPLIED
    assert reconciled.final_content is None


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

    assert pending.final_change_set.changes[0].final_action.value == "UPDATE"
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


def test_complete_valid_run_is_ready_for_write(tmp_path: Path):
    inputs = loaded_inputs(tmp_path, [change()], [reviewed_change("Dots/Topic.md")])

    result = reconcile(inputs)

    assert result.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE
    assert result.final_change_set.validation_findings == []


def test_final_validation_error_makes_change_set_invalid(tmp_path: Path):
    invalid = "---\ntype: map\n---\n# Topic\nWrong type.\n"
    inputs = loaded_inputs(tmp_path, [change(content=invalid)], [reviewed_change("Dots/Topic.md")])

    result = reconcile(inputs)

    assert result.final_change_set.state is FinalChangeSetState.INVALID
    assert result.final_change_set.changes[0].status is ReconciledChangeStatus.INVALID
    assert {item.code for item in result.final_change_set.validation_findings} == {"METADATA"}


def test_pending_change_is_not_invalidated_by_the_issue_waiting_for_human_decision(tmp_path: Path):
    result = reconcile(unresolved_link_inputs(tmp_path))

    assert result.final_change_set.state is FinalChangeSetState.PENDING_HUMAN_REVIEW
    assert not [item for item in result.final_change_set.validation_findings
                if item.severity.value == "ERROR"]


def test_update_paragraph_loss_generates_preservation_decision(tmp_path: Path):
    existing = (
        "---\ntype: concept\n---\n# Topic\n\n"
        "This useful existing paragraph contains durable knowledge that should not silently disappear.\n"
    )
    final = "---\ntype: concept\n---\n# Topic\n\nReplacement.\n"
    inputs = loaded_inputs(
        tmp_path,
        [change(content=final, action="UPDATE",
                original_content_hash=hashlib.sha256(existing.encode()).hexdigest())],
        [reviewed_change("Dots/Topic.md")],
        vault_contents={"Dots/Topic.md": existing},
    )

    result = reconcile(inputs)

    decision = result.final_change_set.human_decisions[0]
    assert decision.id == "HR-001"
    assert decision.category == "cumulative_integrity"
    assert "preserve" in decision.question.casefold()
    assert result.final_change_set.state is FinalChangeSetState.PENDING_HUMAN_REVIEW


def test_resolved_preservation_decision_allows_ready_state_with_audited_warning(tmp_path: Path):
    existing = (
        "---\ntype: concept\n---\n# Topic\n\n"
        "This useful existing paragraph contains durable knowledge that should not silently disappear.\n"
    )
    final = "---\ntype: concept\n---\n# Topic\n\nReplacement.\n"
    inputs = loaded_inputs(
        tmp_path,
        [change(content=final, action="UPDATE",
                original_content_hash=hashlib.sha256(existing.encode()).hexdigest())],
        [reviewed_change("Dots/Topic.md")],
        vault_contents={"Dots/Topic.md": existing},
    )

    result = reconcile(inputs, {"HR-001": "APPLY_RECONCILED_CHANGE"})

    assert result.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE
    assert result.final_change_set.unresolved_decision_ids == []
    assert {item.code for item in result.final_change_set.validation_findings} == {"UPDATE_PARAGRAPH_LOSS"}


def test_link_to_blocked_change_is_exposed_as_dependent_human_decision(tmp_path: Path):
    blocked = change(
        path="Dots/Blocked Target.md",
        action="REVIEW_REQUIRED",
        content="---\ntype: concept\n---\n# Blocked Target\nDraft.\n",
    )
    dependent = change(
        path="Dots/Dependent.md",
        content="---\ntype: concept\n---\n# Dependent\nSee [[Blocked Target]].\n",
    )
    inputs = loaded_inputs(
        tmp_path,
        [blocked, dependent],
        [
            reviewed_change("Dots/Blocked Target.md", status="REVIEW_REQUIRED"),
            reviewed_change("Dots/Dependent.md"),
        ],
    )

    pending = reconcile(inputs)
    resolved = reconcile(inputs, {"HR-001": "DEFER"})

    assert [item.id for item in pending.final_change_set.human_decisions] == ["HR-001"]
    dependency = next(item for item in pending.final_change_set.dependencies
                      if item.source_change_id == "RC-002")
    assert dependency.root_decision_id == "HR-001"
    assert dependency.blocking is True
    assert pending.final_change_set.state is FinalChangeSetState.PENDING_HUMAN_REVIEW
    assert resolved.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE
    assert resolved.final_change_set.changes[1].status is ReconciledChangeStatus.BLOCKED


def test_blocked_link_gets_its_own_decision_when_change_already_has_another_link_issue(
        tmp_path: Path):
    blocked = change(
        path="Dots/Blocked Target.md",
        action="REVIEW_REQUIRED",
        content="---\ntype: concept\n---\n# Blocked Target\nDraft.\n",
    )
    dependent = change(
        path="Dots/Dependent.md",
        content=(
            "---\ntype: concept\n---\n# Dependent\n"
            "See [[Unknown Target]] and [[Blocked Target]].\n"
        ),
    )
    issues = [review_issue(
        "Dots/Dependent.md",
        "link",
        "Use a verified canonical target or remove the link",
        explanation="Unresolved wikilink: [[Unknown Target]]",
    )]
    inputs = loaded_inputs(
        tmp_path,
        [blocked, dependent],
        [
            reviewed_change("Dots/Blocked Target.md", status="REVIEW_REQUIRED"),
            reviewed_change("Dots/Dependent.md", status="FIX", issue_indices=[0]),
        ],
        issues,
    )

    pending = reconcile(inputs)

    dependent_decisions = [
        item for item in pending.final_change_set.human_decisions
        if item.change_ids == ["RC-002"]
    ]
    assert [item.id for item in dependent_decisions] == ["HR-002"]
    assert "[[Unknown Target]]" in dependent_decisions[0].question
    assert any(item.root_decision_id == "HR-001" and item.token == "[[Blocked Target]]"
               for item in pending.final_change_set.dependencies)


def test_dependency_decisions_do_not_cascade_through_still_pending_creates(tmp_path: Path):
    root = change(
        path="Dots/Root.md",
        action="REVIEW_REQUIRED",
        content="---\ntype: concept\n---\n# Root\nDraft.\n",
    )
    middle = change(
        path="Dots/Middle.md",
        content="---\ntype: concept\n---\n# Middle\nSee [[Root]].\n",
    )
    leaf = change(
        path="Dots/Leaf.md",
        content="---\ntype: concept\n---\n# Leaf\nSee [[Middle]].\n",
    )
    inputs = loaded_inputs(
        tmp_path,
        [root, middle, leaf],
        [
            reviewed_change("Dots/Root.md", status="REVIEW_REQUIRED"),
            reviewed_change("Dots/Middle.md"),
            reviewed_change("Dots/Leaf.md"),
        ],
    )

    pending = reconcile(inputs)

    assert [item.change_ids for item in pending.final_change_set.human_decisions] == [
        ["RC-001", "RC-002"]
    ]
    assert pending.final_change_set.changes[2].human_decision_ids == []


def classification_identity_inputs(
        tmp_path: Path, *, existing: str | None = None,
        original_hash: str | None = None, include_semantic_issue: bool = False):
    existing = existing or (
        "---\ntype: concept\naliases: [Classification, Predictive Classifier]\n"
        "maps: []\n---\n# Predictive Classification\n"
        "Classification assigns discrete labels to records.\n"
    )
    original_hash = original_hash or hashlib.sha256(existing.encode()).hexdigest()
    classification = change(
        path="Dots/Classification.md",
        action="REVIEW_REQUIRED",
        content="---\ntype: concept\naliases: []\n---\n# Classification\nNew concept.\n",
    )
    predictive = change(
        path="Dots/Predictive Classification.md",
        action="REVIEW_REQUIRED",
        content="",
        original_content_hash=original_hash,
    )
    dependent = change(
        path="Dots/Dependent.md",
        content="---\ntype: concept\n---\n# Dependent\nSee [[Classification]].\n",
    )
    issues = [
        review_issue(
            "Dots/Classification.md",
            "existing_note",
            "Resolve the original proposal concern before applying",
            explanation="Classification may overlap Predictive Classification.",
        ),
        review_issue(
            "Dots/Predictive Classification.md",
            "existing_note",
            "Resolve the original proposal concern before applying",
            explanation="Predictive Classification currently owns the Classification alias.",
        ),
    ]
    classification_indices = [0]
    if include_semantic_issue:
        classification_indices.append(len(issues))
        issues.append(review_issue(
            "Dots/Classification.md",
            "claim_strength",
            "Confirm the unsupported claim",
            explanation="The staged definition is broader than the supplied evidence.",
        ))
    return loaded_inputs(
        tmp_path,
        [classification, predictive, dependent],
        [
            reviewed_change(
                "Dots/Classification.md", status="REVIEW_REQUIRED",
                issue_indices=classification_indices,
            ),
            reviewed_change(
                "Dots/Predictive Classification.md", status="REVIEW_REQUIRED",
                issue_indices=[1],
            ),
            reviewed_change("Dots/Dependent.md"),
        ],
        issues,
        vault_contents={"Dots/Predictive Classification.md": existing},
    )


def test_classification_identity_uses_one_shared_decision_for_notes_and_dependents(tmp_path: Path):
    result = reconcile(classification_identity_inputs(tmp_path))

    identity_decisions = [
        item for item in result.final_change_set.human_decisions
        if item.category == DecisionCategory.CONCEPT_IDENTITY.value
    ]
    assert len(identity_decisions) == 1
    decision = identity_decisions[0]
    assert decision.change_ids == ["RC-001", "RC-002", "RC-003"]
    assert set(decision.issue_ids) == {"RC-001-I01", "RC-002-I01"}
    assert [option.key for option in decision.options] == ["KEEP_SEPARATE", "DEFER"]
    assert "MERGE" not in {option.key for option in decision.options}
    assert "APPLY_RECONCILED_CHANGE" not in {option.key for option in decision.options}
    assert all(decision.id in item.human_decision_ids
               for item in result.final_change_set.changes[:2])


def test_keep_separate_creates_classification_and_minimally_removes_existing_alias(tmp_path: Path):
    inputs = classification_identity_inputs(tmp_path)
    pending = reconcile(inputs)
    identity = next(item for item in pending.final_change_set.human_decisions
                    if item.category == DecisionCategory.CONCEPT_IDENTITY.value)

    result = reconcile(inputs, {identity.id: "KEEP_SEPARATE"})

    classification, predictive, dependent = result.final_change_set.changes
    assert classification.final_action.value == "CREATE"
    assert predictive.final_action.value == "UPDATE"
    assert predictive.final_content == (
        "---\ntype: concept\naliases: [Predictive Classifier]\n"
        "maps: []\n---\n# Predictive Classification\n"
        "Classification assigns discrete labels to records.\n"
    )
    assert predictive.applied_fixes[-1].before == (
        "aliases: [Classification, Predictive Classifier]"
    )
    assert predictive.applied_fixes[-1].after == "aliases: [Predictive Classifier]"
    assert not [item for item in result.final_change_set.identity_collisions if item.blocking]
    assert dependent.status in {ReconciledChangeStatus.READY, ReconciledChangeStatus.FIXED}
    assert result.final_change_set.state is FinalChangeSetState.READY_FOR_WRITE


@pytest.mark.parametrize(
    ("existing", "original_hash"),
    [
        (
            "---\ntype: concept\naliases: [Classification]\n---\n"
            "# Predictive Classification\nExisting.\n",
            "f" * 64,
        ),
        (
            "---\ntype: concept\naliases: &shared [Classification]\n---\n"
            "# Predictive Classification\nExisting.\n",
            None,
        ),
        (
            "---\ntype: concept\naliases: [Classification, Classification]\n---\n"
            "# Predictive Classification\nExisting.\n",
            None,
        ),
    ],
)
def test_keep_separate_is_not_offered_without_one_safe_exact_alias_patch(
        tmp_path: Path, existing: str, original_hash: str | None):
    inputs = classification_identity_inputs(
        tmp_path, existing=existing, original_hash=original_hash
    )

    result = reconcile(inputs)

    identity = next(item for item in result.final_change_set.human_decisions
                    if item.category == DecisionCategory.CONCEPT_IDENTITY.value)
    assert [option.key for option in identity.options] == ["DEFER"]


def test_conflicting_shared_and_semantic_decisions_are_rejected_independent_of_order(
        tmp_path: Path):
    inputs = classification_identity_inputs(tmp_path, include_semantic_issue=True)
    pending = reconcile(inputs)
    identity = next(item for item in pending.final_change_set.human_decisions
                    if item.category == DecisionCategory.CONCEPT_IDENTITY.value)
    semantic = next(item for item in pending.final_change_set.human_decisions
                    if item.category != DecisionCategory.CONCEPT_IDENTITY.value
                    and "RC-001" in item.change_ids)

    for selections in (
        {identity.id: "KEEP_SEPARATE", semantic.id: "DEFER"},
        {semantic.id: "DEFER", identity.id: "KEEP_SEPARATE"},
    ):
        with pytest.raises(ValueError, match="Conflicting decision effects"):
            reconcile(inputs, selections)
