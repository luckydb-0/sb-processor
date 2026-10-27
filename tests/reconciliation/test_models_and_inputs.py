from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from sb_processor.models import Action
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    AcceptedRisk,
    DecisionCategory,
    DecisionEffect,
    DecisionOption,
    DecisionStatus,
    DependencyRecord,
    DependencyTargetState,
    FinalChangeSet,
    FinalChangeSetState,
    HumanDecision,
    IdentityClaim,
    IdentityClaimKind,
    IdentityCollision,
    IssueResolutionDisposition,
    MaterialLossKind,
    MaterialLossRecord,
)

from .helpers import change, proposal, review, reviewed_change, write_run


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_decision_models_are_strict_and_round_trip_machine_effects():
    decision = HumanDecision(
        id="HR-001",
        change_ids=["RC-001"],
        issue_ids=["RC-001-I01"],
        category="concept_boundary",
        status=DecisionStatus.PENDING,
        question="Should Topic remain separate from Existing Topic?",
        context="The supplied evidence leaves the boundary unresolved.",
        agent_a_position="Create Topic separately.",
        agent_b_position="The concepts may overlap.",
        recommendation="DEFER",
        rationale="No supplied evidence resolves the boundary.",
        confidence="low",
        options=[DecisionOption(key="DEFER", label="Defer this change", effect=DecisionEffect.DEFER)],
    )

    assert HumanDecision.model_validate_json(decision.model_dump_json()) == decision
    assert decision.options[0].effect == DecisionEffect.DEFER
    with pytest.raises(ValidationError):
        HumanDecision.model_validate({**decision.model_dump(), "developer_diagnostic": "forbidden"})


def test_final_change_set_serializes_explicit_state_and_provenance():
    result = FinalChangeSet(
        source_run_id="run_1",
        reconciliation_version="reconciliation-v1",
        provenance={"reviewed_agent_a_proposal": "proposal.json", "agent_b_review": "agent_b/review.json"},
        input_sha256={"proposal.json": "a" * 64, "agent_b/review.json": "b" * 64},
        pre_review_adjustments=[],
        changes=[],
        human_decisions=[],
        unresolved_decision_ids=[],
        validation_findings=[],
        state=FinalChangeSetState.READY_FOR_WRITE,
    )

    payload = result.model_dump(mode="json")
    assert payload["state"] == "READY_FOR_WRITE"
    assert payload["reconciliation_version"] == "reconciliation-v1"


def test_v11_safety_models_round_trip_dependency_identity_loss_and_risk_audit():
    dependency = DependencyRecord(
        id="DEP-RC-001-01",
        source_change_id="RC-001",
        source_path="Atlas/Dots/Data Mining.md",
        token="[[Data Mining - Map]]",
        normalized_target="data mining map",
        target_state=DependencyTargetState.TARGET_CREATED_IN_BATCH,
        target_path="Atlas/Maps/Data Mining - Map.md",
        target_change_id="RC-002",
        blocking=False,
    )
    claim = IdentityClaim(
        value="Classification",
        normalized="classification",
        kind=IdentityClaimKind.ALIAS,
        canonical_path="Atlas/Dots/Predictive Classification.md",
        change_id="RC-002",
        from_existing_vault=True,
    )
    collision = IdentityCollision(
        id="IDENTITY-classification",
        normalized_identity="classification",
        claims=[claim],
        change_ids=["RC-001", "RC-002"],
        dependent_change_ids=["RC-003"],
        blocking=True,
        human_decision_id="HR-001",
    )
    loss = MaterialLossRecord(
        id="LOSS-RC-004-P01",
        change_id="RC-004",
        kind=MaterialLossKind.PARAGRAPH,
        excerpt="Useful existing knowledge.",
        source_content_sha256="a" * 64,
        disposition=IssueResolutionDisposition.ISSUE_EXPLICITLY_ACCEPTED,
        decision_id="HR-002",
    )
    risk = AcceptedRisk(
        id="RISK-HR-002-01",
        category=DecisionCategory.CONTENT_PRESERVATION,
        change_ids=["RC-004"],
        issue_ids=["RC-004-I01"],
        material_loss_ids=[loss.id],
        decision_id="HR-002",
        selected_option="ACKNOWLEDGE_CONTENT_LOSS",
        description="The exact prior paragraph is intentionally omitted.",
        evidence=[loss.excerpt],
    )

    assert DependencyRecord.model_validate_json(dependency.model_dump_json()) == dependency
    assert IdentityCollision.model_validate_json(collision.model_dump_json()) == collision
    assert MaterialLossRecord.model_validate_json(loss.model_dump_json()) == loss
    assert AcceptedRisk.model_validate_json(risk.model_dump_json()) == risk
    assert dependency.target_state.value == "TARGET_CREATED_IN_BATCH"
    assert claim.kind.value == "ALIAS"
    assert loss.disposition.value == "ISSUE_EXPLICITLY_ACCEPTED"


def test_v11_decision_option_records_machine_effect_and_human_consequence():
    option = DecisionOption(
        key="KEEP_SEPARATE",
        label="Keep both concepts separate",
        effect=DecisionEffect.KEEP_SEPARATE,
        consequence=(
            "Create Classification and remove only the conflicting Classification alias "
            "from Predictive Classification."
        ),
    )
    decision = HumanDecision(
        id="HR-001",
        change_ids=["RC-001", "RC-002"],
        issue_ids=["RC-001-I01", "RC-002-I01"],
        category=DecisionCategory.CONCEPT_IDENTITY.value,
        status=DecisionStatus.PENDING,
        question="Should the two concepts remain separate?",
        context="The proposed title collides with an existing alias.",
        agent_a_position="Create Classification separately.",
        agent_b_position="Resolve the identity boundary.",
        options=[option],
        blocking=True,
    )

    assert decision.options[0].consequence.startswith("Create Classification")
    assert decision.blocking is True
    assert HumanDecision.model_validate_json(decision.model_dump_json()) == decision


def test_v11_final_change_set_additive_collections_default_empty_for_v1_payloads():
    result = FinalChangeSet(
        source_run_id="run_1",
        reconciliation_version="reconciliation-v1",
        provenance={},
        input_sha256={},
        pre_review_adjustments=[],
        changes=[],
        human_decisions=[],
        unresolved_decision_ids=[],
        validation_findings=[],
        state=FinalChangeSetState.READY_FOR_WRITE,
    )

    assert result.dependencies == []
    assert result.identity_collisions == []
    assert result.accepted_risks == []
    assert result.applicable_change_ids == []


def test_loader_preserves_original_and_reviewed_proposal_hashes_and_adjustment(tmp_path: Path):
    run = tmp_path / "run_1"
    original = proposal([change(path="Maps/Machine Learning.md", note_type="map",
                                 content="---\ntype: map\n---\n# Machine Learning\n")])
    reviewed = proposal([change(path="Maps/Machine Learning - Map.md", note_type="map",
                                 content="---\ntype: map\n---\n# Machine Learning\n")])
    reviewed["note_changes"][0]["title"] = original["note_changes"][0]["title"]
    result = review([reviewed_change("Maps/Machine Learning - Map.md")])
    write_run(run, reviewed, result, original_proposal=original)
    vault = tmp_path / "vault"
    vault.mkdir()

    loaded = load_reconciliation_inputs(run, vault)

    assert loaded.reviewed_proposal.note_changes[0].target_path == "Maps/Machine Learning - Map.md"
    assert loaded.original_proposal is not None
    assert loaded.original_proposal.note_changes[0].target_path == "Maps/Machine Learning.md"
    assert loaded.input_sha256["proposal.json"] == sha256(run / "proposal.json")
    assert loaded.input_sha256["original_agent_a_proposal.json"] == sha256(run / "original_agent_a_proposal.json")
    assert [item.field for item in loaded.pre_review_adjustments] == ["note_changes[0].target_path"]
    assert loaded.pre_review_adjustments[0].before == "Maps/Machine Learning.md"
    assert loaded.pre_review_adjustments[0].after == "Maps/Machine Learning - Map.md"


def test_loader_uses_reviewed_proposal_as_original_when_no_separate_original_exists(tmp_path: Path):
    run = tmp_path / "run_1"
    data = proposal([change()])
    write_run(run, data, review([reviewed_change("Dots/Topic.md")]))
    vault = tmp_path / "vault"
    vault.mkdir()

    loaded = load_reconciliation_inputs(run, vault)

    assert loaded.original_proposal == loaded.reviewed_proposal
    assert loaded.pre_review_adjustments == []
    assert loaded.provenance["original_agent_a_proposal"] == "proposal.json"


def test_loader_rejects_agent_a_copy_that_differs_from_reviewed_proposal(tmp_path: Path):
    run = tmp_path / "run_1"
    data = proposal([change()])
    write_run(run, data, review([reviewed_change("Dots/Topic.md")]), agent_a_matches=False)
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="agent_a/proposal.json must be byte-identical"):
        load_reconciliation_inputs(run, vault)


def test_loader_rejects_agent_b_change_without_matching_reviewed_proposal(tmp_path: Path):
    run = tmp_path / "run_1"
    data = proposal([change()])
    write_run(run, data, review([reviewed_change("Dots/Other.md")]))
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="Agent B change paths do not match"):
        load_reconciliation_inputs(run, vault)


def test_loader_rejects_agent_b_issue_index_owned_by_another_change(tmp_path: Path):
    run = tmp_path / "run_1"
    changes = [change(path="Dots/One.md"), change(path="Dots/Two.md")]
    issue = {
        "change_path": "Dots/Two.md",
        "issue_type": "claim_strength",
        "severity": "medium",
        "explanation": "Needs correction",
        "proposed_correction": "Confirm the claim",
        "source_pages": [],
        "evidence_refs": [],
        "corrected_content": None,
    }
    write_run(
        run,
        proposal(changes),
        review([
            reviewed_change("Dots/One.md", status="FIX", issue_indices=[0]),
            reviewed_change("Dots/Two.md"),
        ], issues=[issue], overall_status="FIX"),
    )
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="does not belong to reviewed change"):
        load_reconciliation_inputs(run, vault)


def test_loader_rejects_fix_status_without_a_linked_issue(tmp_path: Path):
    run = tmp_path / "run_1"
    write_run(
        run,
        proposal([change()]),
        review([reviewed_change("Dots/Topic.md", status="FIX")], overall_status="FIX"),
    )
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="FIX requires at least one linked issue"):
        load_reconciliation_inputs(run, vault)


def test_loader_rejects_orphaned_agent_b_issue(tmp_path: Path):
    run = tmp_path / "run_1"
    orphan = {
        "change_path": "Dots/Topic.md",
        "issue_type": "claim_strength",
        "severity": "medium",
        "explanation": "Needs correction",
        "proposed_correction": "Confirm the claim",
        "source_pages": [],
        "evidence_refs": [],
        "corrected_content": None,
    }
    write_run(
        run,
        proposal([change()]),
        review([reviewed_change("Dots/Topic.md")], issues=[orphan]),
    )
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="not linked to a reviewed change"):
        load_reconciliation_inputs(run, vault)


def test_loader_rejects_incoherent_agent_b_overall_status(tmp_path: Path):
    run = tmp_path / "run_1"
    write_run(
        run,
        proposal([change()]),
        review([reviewed_change("Dots/Topic.md")], overall_status="FIX"),
    )
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="overall status does not match"):
        load_reconciliation_inputs(run, vault)


def test_loader_validates_original_actions_without_mutating_inputs(tmp_path: Path):
    run = tmp_path / "run_1"
    data = proposal([change(action=Action.CREATE.value)])
    write_run(run, data, review([reviewed_change("Dots/Topic.md")]))
    vault = tmp_path / "vault"
    vault.mkdir()

    loaded = load_reconciliation_inputs(run, vault)

    assert loaded.reviewed_proposal.note_changes[0].action is Action.CREATE
    assert (run / "reconciliation").exists() is False
