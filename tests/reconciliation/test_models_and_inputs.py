from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from sb_processor.models import Action
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    DecisionEffect,
    DecisionOption,
    DecisionStatus,
    FinalChangeSet,
    FinalChangeSetState,
    HumanDecision,
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


def test_loader_validates_original_actions_without_mutating_inputs(tmp_path: Path):
    run = tmp_path / "run_1"
    data = proposal([change(action=Action.CREATE.value)])
    write_run(run, data, review([reviewed_change("Dots/Topic.md")]))
    vault = tmp_path / "vault"
    vault.mkdir()

    loaded = load_reconciliation_inputs(run, vault)

    assert loaded.reviewed_proposal.note_changes[0].action is Action.CREATE
    assert (run / "reconciliation").exists() is False
