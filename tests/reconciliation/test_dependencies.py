from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb_processor.models import Action, ReviewStatus
from sb_processor.reconciliation.dependencies import analyze_dependencies, dependency_findings
from sb_processor.reconciliation.identities import build_effective_identity_registry
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    DependencyTargetState,
    ReconciledChange,
    ReconciledChangeStatus,
)

from .helpers import change, proposal, review, reviewed_change, write_note, write_run


def loaded_inputs(tmp_path: Path, changes: list[dict], vault_contents: dict[str, str] | None = None):
    run = tmp_path / "run"
    write_run(run, proposal(changes), review([
        reviewed_change(item["target_path"]) for item in changes
    ]))
    vault = tmp_path / "vault"
    vault.mkdir()
    for path, content in (vault_contents or {}).items():
        write_note(vault, path, content)
    return load_reconciliation_inputs(run, vault)


def reconciled(
    change_id: str,
    index: int,
    path: str,
    action: Action,
    content: str | None,
    *,
    status: ReconciledChangeStatus = ReconciledChangeStatus.READY,
    decisions: list[str] | None = None,
) -> ReconciledChange:
    return ReconciledChange(
        id=change_id,
        agent_a_change_index=index,
        original_action=action,
        original_target_path=path,
        original_content_sha256=hashlib.sha256((content or "").encode()).hexdigest(),
        agent_b_status=ReviewStatus.PASS,
        human_decision_ids=decisions or [],
        final_action=action,
        final_target_path=path,
        final_content=content,
        final_content_sha256=(hashlib.sha256(content.encode()).hexdigest() if content else None),
        status=status,
    )


def test_same_batch_map_create_resolves_every_occurrence_without_blocking(tmp_path: Path):
    source_one = "---\ntype: concept\n---\n# One\nSee [[Data Mining - Map]].\n"
    source_two = "---\ntype: concept\n---\n# Two\nUse [[Data Mining - Map|the map]].\n"
    target = "---\ntype: map\n---\n# Data Mining - Map\nBody.\n"
    proposal_changes = [
        change(path="Dots/One.md", content=source_one),
        change(path="Dots/Two.md", content=source_two),
        change(path="Maps/Data Mining - Map.md", note_type="map", content=target),
    ]
    inputs = loaded_inputs(tmp_path, proposal_changes)
    changes = [
        reconciled("RC-001", 0, "Dots/One.md", Action.CREATE, source_one),
        reconciled("RC-002", 1, "Dots/Two.md", Action.CREATE, source_two),
        reconciled("RC-003", 2, "Maps/Data Mining - Map.md", Action.CREATE, target),
    ]

    records = analyze_dependencies(
        inputs, changes, build_effective_identity_registry(inputs, changes)
    )

    map_records = [item for item in records if item.normalized_target == "data mining map"]
    assert len(map_records) == 2
    assert {item.target_state for item in map_records} == {
        DependencyTargetState.TARGET_CREATED_IN_BATCH
    }
    assert {item.target_change_id for item in map_records} == {"RC-003"}
    assert all(item.blocking is False for item in map_records)
    assert dependency_findings(map_records) == []


def test_links_resolve_to_existing_vault_and_applicable_update(tmp_path: Path):
    source = (
        "---\ntype: concept\n---\n# Source\n"
        "See [[Existing]] and [[Updated Alias]].\n"
    )
    update = "---\ntype: concept\naliases: [Updated Alias]\n---\n# Updated\nBody.\n"
    proposal_changes = [
        change(path="Dots/Source.md", content=source),
        change(path="Dots/Updated.md", action="UPDATE", content=update),
    ]
    inputs = loaded_inputs(tmp_path, proposal_changes, {
        "Dots/Existing.md": "---\ntype: concept\n---\n# Existing\nBody.\n",
        "Dots/Updated.md": "---\ntype: concept\n---\n# Before\nBody.\n",
    })
    changes = [
        reconciled("RC-001", 0, "Dots/Source.md", Action.CREATE, source),
        reconciled("RC-002", 1, "Dots/Updated.md", Action.UPDATE, update),
    ]

    records = analyze_dependencies(
        inputs, changes, build_effective_identity_registry(inputs, changes)
    )

    states = {item.normalized_target: item.target_state for item in records}
    assert states == {
        "existing": DependencyTargetState.TARGET_EXISTS_IN_VAULT,
        "updated alias": DependencyTargetState.TARGET_UPDATED_IN_BATCH,
    }


def test_explicit_full_path_disambiguates_duplicate_basenames(tmp_path: Path):
    source = "---\ntype: concept\n---\n# Source\nSee [[Area A/Topic]].\n"
    inputs = loaded_inputs(tmp_path, [change(path="Dots/Source.md", content=source)], {
        "Area A/Topic.md": "---\ntype: concept\n---\n# First Topic\nA.\n",
        "Area B/Topic.md": "---\ntype: concept\n---\n# Second Topic\nB.\n",
    })
    changes = [reconciled("RC-001", 0, "Dots/Source.md", Action.CREATE, source)]

    record = analyze_dependencies(
        inputs, changes, build_effective_identity_registry(inputs, changes)
    )[0]

    assert record.target_path == "Area A/Topic.md"
    assert record.target_state is DependencyTargetState.TARGET_EXISTS_IN_VAULT
    assert record.blocking is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ReconciledChangeStatus.BLOCKED, DependencyTargetState.TARGET_DEFERRED),
        (ReconciledChangeStatus.DEFERRED, DependencyTargetState.TARGET_DEFERRED),
        (ReconciledChangeStatus.SKIPPED, DependencyTargetState.TARGET_SKIPPED),
    ],
)
def test_excluded_batch_create_blocks_dependents_without_rewriting_link(
        tmp_path: Path, status: ReconciledChangeStatus,
        expected: DependencyTargetState):
    source = "---\ntype: concept\n---\n# Source\nSee [[Target]].\n"
    target = "---\ntype: concept\n---\n# Target\nDraft.\n"
    inputs = loaded_inputs(tmp_path, [
        change(path="Dots/Source.md", content=source),
        change(path="Dots/Target.md", content=target),
    ])
    changes = [
        reconciled("RC-001", 0, "Dots/Source.md", Action.CREATE, source),
        reconciled("RC-002", 1, "Dots/Target.md", Action.CREATE, target,
                   status=status, decisions=["HR-001"]),
    ]

    records = analyze_dependencies(
        inputs, changes, build_effective_identity_registry(inputs, changes)
    )

    source_record = next(item for item in records if item.source_change_id == "RC-001")
    assert source_record.target_state is expected
    assert source_record.blocking is True
    assert source_record.root_decision_id == "HR-001"
    assert changes[0].final_content == source
    assert dependency_findings([source_record])[0].code == "UNRESOLVED_REQUIRED_DEPENDENCY"


def test_missing_and_ambiguous_targets_are_blocking(tmp_path: Path):
    source = "---\ntype: concept\n---\n# Source\nSee [[Missing]] and [[Shared]].\n"
    inputs = loaded_inputs(tmp_path, [change(path="Dots/Source.md", content=source)], {
        "Dots/One.md": "---\ntype: concept\naliases: [Shared]\n---\n# One\nA.\n",
        "Dots/Two.md": "---\ntype: concept\naliases: [Shared]\n---\n# Two\nB.\n",
    })
    changes = [reconciled("RC-001", 0, "Dots/Source.md", Action.CREATE, source)]

    records = analyze_dependencies(
        inputs, changes, build_effective_identity_registry(inputs, changes)
    )

    states = {item.normalized_target: item.target_state for item in records}
    assert states == {
        "missing": DependencyTargetState.TARGET_MISSING,
        "shared": DependencyTargetState.TARGET_AMBIGUOUS,
    }
    assert len(dependency_findings(records)) == 2
    assert all(item.blocking for item in records)
