from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from sb_processor.reconciliation.artifacts import run_reconciliation, stage_reconciliation
from sb_processor.reconciliation.engine import reconcile
from sb_processor.reconciliation.inputs import load_reconciliation_inputs

from .helpers import change, proposal, review, review_issue, reviewed_change, write_note, write_run


def artifact_fixture(tmp_path: Path):
    run = tmp_path / "run_1"
    existing = (
        "---\ntype: concept\n---\n# Existing\n\n"
        "A durable existing paragraph that remains intact through the proposed update.\n"
    )
    updated = existing + "\nA new supported sentence.\n"
    changes = [
        change(path="Dots/New Topic.md", content="---\ntype: concept\n---\n# New Topic\nNew body.\n"),
        change(path="Dots/Existing.md", action="UPDATE", content=updated,
               original_content_hash=hashlib.sha256(existing.encode()).hexdigest()),
        change(path="Dots/Blocked.md", content=(
            "---\ntype: concept\n---\n# Blocked\nSee [[Missing]].\n"
        )),
    ]
    issues = [review_issue(
        "Dots/Blocked.md",
        "link",
        "Use a verified canonical target or remove the link",
        explanation="Unresolved wikilink: [[Missing]]",
    )]
    reviewed = [
        reviewed_change("Dots/New Topic.md"),
        reviewed_change("Dots/Existing.md"),
        reviewed_change("Dots/Blocked.md", status="FIX", issue_indices=[0]),
    ]
    write_run(run, proposal(changes), review(reviewed, issues=issues, overall_status="FIX"))
    vault = tmp_path / "vault"
    vault.mkdir()
    write_note(vault, "Dots/Existing.md", existing)
    inputs = load_reconciliation_inputs(run, vault)
    return run, inputs, reconcile(inputs)


def test_stage_reconciliation_writes_only_canonical_artifacts_under_reconciliation(tmp_path: Path):
    run, inputs, result = artifact_fixture(tmp_path)
    before = {path.relative_to(run).as_posix() for path in run.rglob("*")}

    output = stage_reconciliation(run, result, inputs)

    assert output == run / "reconciliation"
    files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    assert files == {
        "HUMAN_REVIEW.md",
        "WRITE_PREVIEW.md",
        "diffs/RC-002.diff",
        "final_change_set.json",
        "human_decisions.json",
        "reconciliation.json",
    }
    added_outside = {
        path.relative_to(run).as_posix() for path in run.rglob("*")
        if path.relative_to(run).as_posix() not in before
        and not path.relative_to(run).as_posix().startswith("reconciliation")
    }
    assert added_outside == set()


def test_human_review_is_concise_and_contains_machine_matching_decisions(tmp_path: Path):
    run, inputs, result = artifact_fixture(tmp_path)

    output = stage_reconciliation(run, result, inputs)

    markdown = (output / "HUMAN_REVIEW.md").read_text(encoding="utf-8")
    machine = json.loads((output / "human_decisions.json").read_text(encoding="utf-8"))
    assert "Automatically ready: 2" in markdown
    assert "Needs your decision: 1" in markdown
    assert "HR-001" in markdown
    assert "Should `Dots/Blocked.md` keep the unresolved wikilink `[[Missing]]`?" in markdown
    assert "APPLY_RECONCILED_CHANGE" in markdown
    assert "developer" not in markdown.casefold()
    assert machine["decisions"][0]["id"] == "HR-001"
    assert machine["decisions"][0]["status"] == "PENDING"
    assert machine["decisions"][0]["selected_option"] is None
    assert [item["key"] for item in machine["decisions"][0]["options"]] == [
        "APPLY_RECONCILED_CHANGE", "REMOVE_LINK", "SKIP_CHANGE", "DEFER"
    ]


def test_resolved_human_review_lists_only_pending_decisions(tmp_path: Path):
    run, inputs, _ = artifact_fixture(tmp_path)
    result = reconcile(inputs, {"HR-001": "DEFER"})

    output = stage_reconciliation(run, result, inputs)

    markdown = (output / "HUMAN_REVIEW.md").read_text(encoding="utf-8")
    assert "Needs your decision: 0" in markdown
    assert "Resolved or deferred decisions: 1" in markdown
    assert "### HR-001" not in markdown
    assert "human_decisions.json" in markdown


def test_write_preview_groups_actions_and_links_stable_update_diff(tmp_path: Path):
    run, inputs, result = artifact_fixture(tmp_path)

    output = stage_reconciliation(run, result, inputs)

    preview = (output / "WRITE_PREVIEW.md").read_text(encoding="utf-8")
    diff = (output / "diffs" / "RC-002.diff").read_text(encoding="utf-8")
    assert "## CREATE" in preview
    assert "`Dots/New Topic.md`" in preview
    assert "## UPDATE" in preview
    assert "`Dots/Existing.md` — [diff](diffs/RC-002.diff)" in preview
    assert "## BLOCKED" in preview
    assert "`Dots/Blocked.md` — HR-001 pending" in preview
    assert "--- a/Dots/Existing.md" in diff
    assert "+++ b/Dots/Existing.md" in diff
    assert "+A new supported sentence." in diff


def test_json_artifacts_share_the_same_final_change_set_state(tmp_path: Path):
    run, inputs, result = artifact_fixture(tmp_path)

    output = stage_reconciliation(run, result, inputs)

    reconciliation = json.loads((output / "reconciliation.json").read_text(encoding="utf-8"))
    final = json.loads((output / "final_change_set.json").read_text(encoding="utf-8"))
    assert reconciliation["final_change_set"] == final
    assert final["state"] == "PENDING_HUMAN_REVIEW"


def test_decision_file_path_and_hash_are_preserved_in_final_provenance(tmp_path: Path):
    run, inputs, _ = artifact_fixture(tmp_path)
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({"HR-001": "DEFER"}) + "\n", encoding="utf-8")

    final = run_reconciliation(run, inputs.vault, decisions)

    assert final.provenance["human_decisions"] == str(decisions.resolve())
    assert final.input_sha256["human_decisions.json"] == hashlib.sha256(
        decisions.read_bytes()
    ).hexdigest()


def test_staging_rejects_update_target_changed_after_reconciliation(tmp_path: Path):
    run, inputs, result = artifact_fixture(tmp_path)
    write_note(
        inputs.vault,
        "Dots/Existing.md",
        "---\ntype: concept\n---\n# Existing\nChanged after reconciliation.\n",
    )

    with pytest.raises(ValueError, match="Vault UPDATE target changed"):
        stage_reconciliation(run, result, inputs)
