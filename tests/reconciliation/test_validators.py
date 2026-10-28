from __future__ import annotations

import hashlib
from pathlib import Path

from sb_processor.models import IssueType
from sb_processor.reconciliation.engine import reconcile
from sb_processor.reconciliation.inputs import load_reconciliation_inputs, resolve_vault_target
from sb_processor.reconciliation.models import (
    AcceptedRisk,
    DecisionCategory,
    DependencyRecord,
    DependencyTargetState,
    IdentityCollision,
    MaterialLossKind,
    MaterialLossRecord,
    PatchKind,
    PatchOperation,
    ReconciledIssue,
    ValidationFinding,
    ValidationSeverity,
)
from sb_processor.reconciliation.validators import (
    material_losses,
    validate_decision_references,
    validate_final_changes,
)

from .helpers import change, proposal, review, reviewed_change, write_note, write_run


VALID_CONTENT = "---\ntype: concept\n---\n# Topic\nA supported reusable explanation.\n"


def validation_case(tmp_path: Path, *, content: str = VALID_CONTENT, action: str = "CREATE",
                    path: str = "Dots/Topic.md", vault_contents: dict[str, str] | None = None,
                    original_content_hash: str | None = None):
    run = tmp_path / "run_1"
    write_run(run, proposal([change(path=path, action=action, content=content,
                                    original_content_hash=original_content_hash)]),
              review([reviewed_change(path)]))
    vault = tmp_path / "vault"
    vault.mkdir()
    for note_path, note_content in (vault_contents or {}).items():
        write_note(vault, note_path, note_content)
    inputs = load_reconciliation_inputs(run, vault)
    result = reconcile(inputs)
    return inputs, result.final_change_set.changes


def error_codes(findings):
    return {item.code for item in findings if item.severity.value == "ERROR"}


def warning_codes(findings):
    return {item.code for item in findings if item.severity.value == "WARNING"}


def retarget(change_model, *, change_id: str, path: str, action: str | None = None,
             content: str | None = None):
    copied = change_model.model_copy(deep=True)
    copied.id = change_id
    copied.final_target_path = path
    if action is not None:
        copied.final_action = action
    if content is not None:
        copied.final_content = content
        copied.final_content_sha256 = hashlib.sha256(content.encode()).hexdigest()
    return copied


def test_decision_reference_integrity_reports_every_dangling_origin_deterministically(
        tmp_path: Path):
    inputs, _ = validation_case(tmp_path)
    final = reconcile(inputs).final_change_set
    change_model = final.changes[0]
    change_model.human_decision_ids.append("HR-CHANGE")
    change_model.issues.append(ReconciledIssue(
        id="RC-001-I99",
        agent_b_issue_index=-1,
        issue_type=IssueType.LINK,
        explanation="Injected integrity fixture",
        proposed_correction="Resolve the fixture",
        classification="AMBIGUOUS",
        outcome="HUMAN_REQUIRED",
        human_decision_id="HR-ISSUE",
    ))
    change_model.dependencies.append(DependencyRecord(
        id="DEP-INTEGRITY",
        source_change_id=change_model.id,
        source_path=change_model.original_target_path,
        token="[[Target]]",
        normalized_target="target",
        target_state=DependencyTargetState.TARGET_MISSING,
        blocking=True,
        root_decision_id="HR-DEPENDENCY",
    ))
    final.dependencies = list(change_model.dependencies)
    final.identity_collisions.append(IdentityCollision(
        id="IDENTITY-INTEGRITY",
        normalized_identity="identity",
        claims=[],
        blocking=True,
        human_decision_id="HR-COLLISION",
    ))
    change_model.material_losses.append(MaterialLossRecord(
        id="LOSS-INTEGRITY",
        change_id=change_model.id,
        kind=MaterialLossKind.PARAGRAPH,
        excerpt="Material knowledge",
        source_content_sha256="0" * 64,
        decision_id="HR-LOSS",
    ))
    final.accepted_risks.append(AcceptedRisk(
        id="RISK-INTEGRITY",
        category=DecisionCategory.CONTENT_PRESERVATION,
        change_ids=[change_model.id],
        decision_id="HR-RISK",
        selected_option="ACKNOWLEDGE_CONTENT_LOSS",
        description="Injected integrity fixture",
    ))
    final.unresolved_decision_ids.append("HR-UNRESOLVED")
    final.decision_id_remap["HR-OLD"] = "HR-REMAP"

    findings = validate_decision_references(final)

    assert [item.code for item in findings] == [
        "DANGLING_HUMAN_DECISION_REFERENCE",
    ] * 9
    assert [item.message for item in findings] == [
        "accepted_risks[RISK-INTEGRITY].decision_id references missing HR-RISK",
        "changes[RC-001].dependencies[DEP-INTEGRITY].root_decision_id references missing HR-DEPENDENCY",
        "changes[RC-001].human_decision_ids references missing HR-CHANGE",
        "changes[RC-001].issues[RC-001-I99].human_decision_id references missing HR-ISSUE",
        "changes[RC-001].material_losses[LOSS-INTEGRITY].decision_id references missing HR-LOSS",
        "decision_id_remap[HR-OLD] references missing HR-REMAP",
        "dependencies[DEP-INTEGRITY].root_decision_id references missing HR-DEPENDENCY",
        "identity_collisions[IDENTITY-INTEGRITY].human_decision_id references missing HR-COLLISION",
        "unresolved_decision_ids references missing HR-UNRESOLVED",
    ]
    assert all(item.severity.value == "ERROR" for item in findings)


def test_decision_reference_error_forces_engine_state_invalid(
        tmp_path: Path, monkeypatch):
    inputs, _ = validation_case(tmp_path)
    integrity_error = ValidationFinding(
        code="DANGLING_HUMAN_DECISION_REFERENCE",
        severity=ValidationSeverity.ERROR,
        message="changes[RC-001].human_decision_ids references missing HR-404",
        change_ids=["RC-001"],
    )
    monkeypatch.setattr(
        "sb_processor.reconciliation.engine.validate_decision_references",
        lambda _final: [integrity_error],
    )

    final = reconcile(inputs).final_change_set

    assert final.state.value == "INVALID"
    assert integrity_error in final.validation_findings
    assert integrity_error in final.changes[0].validation_findings


def test_path_traversal_is_invalid(tmp_path: Path):
    inputs, changes = validation_case(tmp_path, path="../escape.md")

    findings = validate_final_changes(inputs, changes)

    assert "INVALID_TARGET_PATH" in error_codes(findings)


def test_symlink_escape_is_invalid_and_never_resolves_as_a_vault_target(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text(VALID_CONTENT, encoding="utf-8")
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "Escape.md").symlink_to(outside)
    run = tmp_path / "run_1"
    write_run(
        run,
        proposal([change(path="Dots/Escape.md", action="UPDATE", content=VALID_CONTENT,
                         original_content_hash=hashlib.sha256(VALID_CONTENT.encode()).hexdigest())]),
        review([reviewed_change("Dots/Escape.md")]),
    )
    inputs = load_reconciliation_inputs(run, vault)
    changes = reconcile(inputs).final_change_set.changes

    findings = validate_final_changes(inputs, changes)

    assert resolve_vault_target(vault, "Dots/Escape.md") is None
    assert "INVALID_TARGET_PATH" in error_codes(findings)


def test_note_type_must_use_the_university_workflow_root(tmp_path: Path):
    inputs, changes = validation_case(tmp_path, path="Maps/Topic.md")

    findings = validate_final_changes(inputs, changes)

    assert "INVALID_CANONICAL_TARGET" in error_codes(findings)


def test_missing_content_is_invalid_for_create(tmp_path: Path):
    inputs, changes = validation_case(tmp_path)
    changes[0].final_content = ""
    changes[0].final_content_sha256 = None

    findings = validate_final_changes(inputs, changes)

    assert "MISSING_FINAL_CONTENT" in error_codes(findings)


def test_frontmatter_must_be_valid_and_match_note_type(tmp_path: Path):
    malformed_inputs, malformed = validation_case(tmp_path / "bad", content="---\ntype: [\n---\n# Topic\nBody\n")
    wrong_inputs, wrong = validation_case(tmp_path / "wrong", content="---\ntype: map\n---\n# Topic\nBody\n")

    malformed_findings = validate_final_changes(malformed_inputs, malformed)
    wrong_findings = validate_final_changes(wrong_inputs, wrong)

    assert "METADATA" in error_codes(malformed_findings)
    assert "METADATA" in error_codes(wrong_findings)


def test_provenance_rejects_direct_pdf_metadata_in_concept(tmp_path: Path):
    content = (
        "---\ntype: concept\nsource_file: lecture.pdf\n---\n# Topic\nBody\n"
        "## Sources\n**Location:** /tmp/lecture.pdf\n"
    )
    inputs, changes = validation_case(tmp_path, content=content)

    findings = validate_final_changes(inputs, changes)

    assert "PROVENANCE" in error_codes(findings)


def test_workflow_language_is_invalid_in_final_content(tmp_path: Path):
    content = "---\ntype: concept\n---\n# Topic\nAgent A created this in the current batch.\n"
    inputs, changes = validation_case(tmp_path, content=content)

    findings = validate_final_changes(inputs, changes)

    assert "WORKFLOW_CONTAMINATION" in error_codes(findings)


def test_link_must_resolve_against_vault_or_final_create_targets(tmp_path: Path):
    content = "---\ntype: concept\n---\n# Topic\nSee [[Missing Concept]].\n"
    inputs, changes = validation_case(tmp_path, content=content)

    findings = validate_final_changes(inputs, changes)

    assert changes[0].status.value == "BLOCKED"
    assert changes[0].dependencies[0].target_state.value == "TARGET_MISSING"
    assert changes[0].dependencies[0].blocking is True
    assert "LINK" not in error_codes(findings)


def test_action_must_match_target_existence(tmp_path: Path):
    create_inputs, create_changes = validation_case(
        tmp_path / "create", vault_contents={"Dots/Topic.md": VALID_CONTENT}
    )
    update_inputs, update_changes = validation_case(
        tmp_path / "update", action="UPDATE"
    )

    create_findings = validate_final_changes(create_inputs, create_changes)
    update_findings = validate_final_changes(update_inputs, update_changes)

    assert "CREATE_TARGET_EXISTS" in error_codes(create_findings)
    assert "UPDATE_TARGET_MISSING" in error_codes(update_findings)


def test_update_rejects_vault_content_changed_since_agent_a_snapshot(tmp_path: Path):
    reviewed_existing = "---\ntype: concept\n---\n# Topic\nReviewed existing body.\n"
    current_existing = "---\ntype: concept\n---\n# Topic\nChanged after review.\n"
    inputs, changes = validation_case(
        tmp_path,
        action="UPDATE",
        vault_contents={"Dots/Topic.md": current_existing},
        original_content_hash=hashlib.sha256(reviewed_existing.encode()).hexdigest(),
    )

    findings = validate_final_changes(inputs, changes)

    assert changes[0].expected_existing_content_sha256 == hashlib.sha256(
        reviewed_existing.encode()
    ).hexdigest()
    assert "UPDATE_SOURCE_HASH_MISMATCH" in error_codes(findings)


def test_update_requires_agent_a_snapshot_hash(tmp_path: Path):
    inputs, changes = validation_case(
        tmp_path,
        action="UPDATE",
        vault_contents={"Dots/Topic.md": VALID_CONTENT},
    )

    findings = validate_final_changes(inputs, changes)

    assert "UPDATE_SOURCE_HASH_MISSING" in error_codes(findings)


def test_claimed_fix_is_invalid_when_removed_marker_remains(tmp_path: Path):
    inputs, changes = validation_case(tmp_path)
    changes[0].applied_fixes = [PatchOperation(
        kind=PatchKind.REMOVE,
        start=0,
        end=len("supported"),
        before="supported",
        after="",
    )]

    findings = validate_final_changes(inputs, changes)

    assert "CLAIMED_FIX_REMAINS" in error_codes(findings)


def test_duplicate_target_conflict_is_detected(tmp_path: Path):
    inputs, changes = validation_case(tmp_path)
    duplicate = retarget(changes[0], change_id="RC-002", path="Dots/Topic.md")

    findings = validate_final_changes(inputs, [changes[0], duplicate])

    assert "DUPLICATE_TARGET_PATH" in error_codes(findings)


def test_create_update_conflict_and_divergent_content_are_detected(tmp_path: Path):
    existing = "---\ntype: concept\n---\n# Topic\nExisting reusable paragraph with enough detail to preserve.\n"
    inputs, changes = validation_case(tmp_path, vault_contents={"Dots/Topic.md": existing})
    create = changes[0]
    update_content = "---\ntype: concept\n---\n# Topic\nDifferent final body.\n"
    update = retarget(create, change_id="RC-002", path="Dots/Topic.md", action="UPDATE",
                      content=update_content)

    findings = validate_final_changes(inputs, [create, update])

    assert "CONFLICTING_ACTIONS" in error_codes(findings)
    assert "CONFLICTING_CONTENT" in error_codes(findings)


def test_duplicate_normalized_target_identity_is_detected(tmp_path: Path):
    inputs, changes = validation_case(tmp_path, path="Dots/Data-Set.md")
    variant = retarget(changes[0], change_id="RC-002", path="Dots/Data Set.md")

    findings = validate_final_changes(inputs, [changes[0], variant])

    assert "DUPLICATE_CANONICAL_TARGET" in error_codes(findings)


def test_map_dot_basename_conflict_requires_map_suffix(tmp_path: Path):
    inputs, changes = validation_case(tmp_path, path="Dots/Machine Learning.md")
    map_content = "---\ntype: map\n---\n# Machine Learning\nMap body.\n"
    map_change = retarget(changes[0], change_id="RC-002", path="Maps/Machine Learning.md",
                          content=map_content)
    source = inputs.reviewed_proposal.note_changes[0]
    source.note_type = "map"

    findings = validate_final_changes(inputs, [changes[0], map_change])

    assert "MAP_DOT_BASENAME_CONFLICT" in error_codes(findings)


def test_update_preservation_accepts_retained_heading_and_paragraph(tmp_path: Path):
    existing = (
        "---\ntype: concept\n---\n# Topic\n\n## Definition\n\n"
        "A useful existing paragraph that contains durable knowledge for this concept.\n"
    )
    final = existing + "\n## More\n\nNew supported detail.\n"
    inputs, changes = validation_case(tmp_path, content=final, action="UPDATE",
                                      vault_contents={"Dots/Topic.md": existing})
    changes[0].status = "READY"

    findings = validate_final_changes(inputs, changes)

    assert "UPDATE_HEADING_LOSS" not in warning_codes(findings)
    assert "UPDATE_PARAGRAPH_LOSS" not in warning_codes(findings)


def test_update_preservation_accepts_high_similarity_paragraph(tmp_path: Path):
    existing = (
        "---\ntype: concept\n---\n# Topic\n\n"
        "This useful existing paragraph explains durable knowledge with careful and precise wording.\n"
    )
    final = existing.replace("precise wording", "precise phrasing")
    inputs, changes = validation_case(tmp_path, content=final, action="UPDATE",
                                      vault_contents={"Dots/Topic.md": existing})

    findings = validate_final_changes(inputs, changes)

    assert "UPDATE_PARAGRAPH_LOSS" not in warning_codes(findings)


def test_update_preservation_accepts_audited_local_deletion(tmp_path: Path):
    existing = (
        "---\ntype: concept\n---\n# Topic\n\n"
        "This useful paragraph discusses machine learning and data mining in one sentence.\n"
    )
    final = existing.replace("and data mining", "")
    inputs, changes = validation_case(tmp_path, content=final, action="UPDATE",
                                      vault_contents={"Dots/Topic.md": existing})
    changes[0].applied_fixes = [PatchOperation(
        kind=PatchKind.REMOVE,
        start=existing.index("and data mining"),
        end=existing.index("and data mining") + len("and data mining"),
        before="and data mining",
        after="",
    )]

    findings = validate_final_changes(inputs, changes)

    assert "UPDATE_PARAGRAPH_LOSS" not in warning_codes(findings)


def test_unexplained_heading_and_paragraph_loss_requires_preservation_review(tmp_path: Path):
    existing = (
        "---\ntype: concept\n---\n# Topic\n\n## Important Context\n\n"
        "This useful existing paragraph contains durable knowledge that should not silently disappear.\n"
    )
    final = "---\ntype: concept\n---\n# Topic\n\nReplacement.\n"
    inputs, changes = validation_case(tmp_path, content=final, action="UPDATE",
                                      vault_contents={"Dots/Topic.md": existing})
    changes[0].status = "READY"

    findings = validate_final_changes(inputs, changes)

    assert "UPDATE_HEADING_LOSS" in warning_codes(findings)
    assert "UPDATE_PARAGRAPH_LOSS" in warning_codes(findings)

    losses = material_losses(inputs, changes[0])
    assert [item.id for item in losses] == ["LOSS-RC-001-01", "LOSS-RC-001-02"]
    assert [item.kind.value for item in losses] == ["HEADING", "PARAGRAPH"]
    assert losses[0].excerpt == "Important Context"
    assert losses[1].excerpt == (
        "This useful existing paragraph contains durable knowledge that should not "
        "silently disappear."
    )
    assert all(item.source_content_sha256 == hashlib.sha256(existing.encode()).hexdigest()
               for item in losses)
