from __future__ import annotations

import hashlib
from pathlib import Path

from sb_processor.models import Action, ReviewStatus
from sb_processor.reconciliation.identities import build_effective_identity_registry
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import (
    IdentityClaimKind,
    ReconciledChange,
    ReconciledChangeStatus,
)

from .helpers import change, proposal, review, reviewed_change, write_note, write_run


def loaded_inputs(tmp_path: Path, changes: list[dict], vault_contents: dict[str, str]):
    run = tmp_path / "run"
    reviewed = [reviewed_change(item["target_path"]) for item in changes]
    write_run(run, proposal(changes), review(reviewed))
    vault = tmp_path / "vault"
    vault.mkdir()
    for path, content in vault_contents.items():
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
) -> ReconciledChange:
    return ReconciledChange(
        id=change_id,
        agent_a_change_index=index,
        original_action=action,
        original_target_path=path,
        original_content_sha256=hashlib.sha256((content or "").encode()).hexdigest(),
        agent_b_status=ReviewStatus.PASS,
        final_action=action,
        final_target_path=path,
        final_content=content,
        final_content_sha256=(hashlib.sha256(content.encode()).hexdigest() if content else None),
        status=status,
    )


def test_effective_registry_includes_complete_vault_create_and_update_identities(tmp_path: Path):
    updated = "---\ntype: concept\naliases: [Fresh Alias]\n---\n# Renamed Existing\nBody.\n"
    created = "---\ntype: concept\naliases: [Class]\n---\n# Classification\nBody.\n"
    inputs = loaded_inputs(
        tmp_path,
        [
            change(path="Dots/Existing.md", action="UPDATE", content=updated),
            change(path="Dots/Classification.md", content=created),
        ],
        {
            "Dots/Existing.md": "---\ntype: concept\naliases: [Old Alias]\n---\n# Existing\nOld.\n",
            "Dots/Unrelated.md": "---\ntype: concept\naliases: [Background]\n---\n# Unrelated\nBody.\n",
        },
    )

    analysis = build_effective_identity_registry(inputs, [
        reconciled("RC-001", 0, "Dots/Existing.md", Action.UPDATE, updated),
        reconciled("RC-002", 1, "Dots/Classification.md", Action.CREATE, created),
    ])

    claims = {(item.canonical_path, item.kind, item.normalized) for item in analysis.claims}
    assert ("Dots/Existing.md", IdentityClaimKind.TITLE, "renamed existing") in claims
    assert ("Dots/Existing.md", IdentityClaimKind.ALIAS, "fresh alias") in claims
    assert ("Dots/Existing.md", IdentityClaimKind.ALIAS, "old alias") not in claims
    assert ("Dots/Classification.md", IdentityClaimKind.CANONICAL_PATH,
            "dots classification") in claims
    assert ("Dots/Classification.md", IdentityClaimKind.BASENAME, "classification") in claims
    assert ("Dots/Unrelated.md", IdentityClaimKind.ALIAS, "background") in claims


def test_deferred_update_retains_existing_title_and_aliases(tmp_path: Path):
    proposed = "---\ntype: concept\naliases: []\n---\n# Renamed\nDraft.\n"
    inputs = loaded_inputs(
        tmp_path,
        [change(path="Dots/Predictive Classification.md", action="UPDATE", content=proposed)],
        {
            "Dots/Predictive Classification.md": (
                "---\ntype: concept\naliases: [Classification]\n---\n"
                "# Predictive Classification\nExisting.\n"
            ),
        },
    )

    analysis = build_effective_identity_registry(inputs, [reconciled(
        "RC-001",
        0,
        "Dots/Predictive Classification.md",
        Action.UPDATE,
        None,
        status=ReconciledChangeStatus.DEFERRED,
    )])

    claims = {(item.kind, item.normalized) for item in analysis.claims}
    assert (IdentityClaimKind.TITLE, "predictive classification") in claims
    assert (IdentityClaimKind.ALIAS, "classification") in claims
    assert (IdentityClaimKind.TITLE, "renamed") not in claims


def test_proposed_create_colliding_with_existing_alias_is_blocking(tmp_path: Path):
    created = "---\ntype: concept\naliases: []\n---\n# Classification\nBody.\n"
    inputs = loaded_inputs(
        tmp_path,
        [change(path="Dots/Classification.md", content=created)],
        {
            "Dots/Predictive Classification.md": (
                "---\ntype: concept\naliases: [Classification]\n---\n"
                "# Predictive Classification\nExisting.\n"
            ),
        },
    )

    analysis = build_effective_identity_registry(inputs, [
        reconciled("RC-001", 0, "Dots/Classification.md", Action.CREATE, created),
    ])

    collision = next(item for item in analysis.collisions
                     if item.normalized_identity == "classification")
    assert collision.blocking is True
    assert collision.change_ids == ["RC-001"]
    assert {item.canonical_path for item in collision.claims} == {
        "Dots/Classification.md",
        "Dots/Predictive Classification.md",
    }


def test_same_note_duplicate_claims_do_not_collide_and_existing_only_collision_is_audit_only(
        tmp_path: Path):
    inputs = loaded_inputs(
        tmp_path,
        [],
        {
            "Dots/One.md": "---\ntype: concept\naliases: [Shared, One]\n---\n# Shared\nOne.\n",
            "Archive/Two.md": "---\ntype: concept\naliases: []\n---\n# Shared\nTwo.\n",
        },
    )

    analysis = build_effective_identity_registry(inputs, [])

    shared = [item for item in analysis.collisions if item.normalized_identity == "shared"]
    assert len(shared) == 1
    assert shared[0].blocking is False
    assert shared[0].change_ids == []
    assert {item.canonical_path for item in shared[0].claims} == {
        "Archive/Two.md",
        "Dots/One.md",
    }
    assert not any(
        len({claim.canonical_path for claim in collision.claims}) == 1
        for collision in analysis.collisions
    )
