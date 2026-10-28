from __future__ import annotations

import hashlib
from pathlib import Path

from sb_processor.reconciliation.artifacts import stage_reconciliation
from sb_processor.reconciliation.engine import reconcile
from sb_processor.reconciliation.inputs import load_reconciliation_inputs
from sb_processor.reconciliation.models import FinalChangeSetState

from .helpers import change, proposal, review, reviewed_change, write_note, write_run


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_empty_valid_batch_is_explicitly_not_ready_for_write(tmp_path: Path):
    run = tmp_path / "empty_run"
    write_run(run, proposal([]), review([]))
    vault = tmp_path / "empty_vault"
    vault.mkdir()
    inputs = load_reconciliation_inputs(run, vault)

    result = reconcile(inputs)

    assert result.final_change_set.state is FinalChangeSetState.NO_APPLICABLE_CHANGES
    assert result.final_change_set.applicable_change_ids == []
    assert result.final_change_set.validation_findings == []


def test_real_create_and_update_batch_is_nonempty_ready_and_renders_diff(tmp_path: Path):
    lecture_title = "Machine Learning - 01 - Introduction"
    existing = (
        "---\ntype: concept\naliases: [Established Concept]\nmaps: []\n---\n"
        "# Existing Concept\n\n"
        "A durable existing paragraph explains the established concept and must remain intact.\n"
    )
    created = (
        "---\ntype: concept\naliases: [Novel Concept]\nmaps: []\n---\n"
        "# New Concept\n\n"
        "A reusable explanation connects this concept to [[Existing Concept]].\n\n"
        "## Sources\n\n"
        f"### [[{lecture_title}]]\n\n"
        "**Pages/slides:** 12\n"
    )
    updated = (
        existing
        + "\n## Relationship\n\n"
        + "The established concept now relates to [[New Concept]] without replacing prior knowledge.\n\n"
        + "## Sources\n\n"
        + f"### [[{lecture_title}]]\n\n"
        + "**Pages/slides:** 12\n"
    )
    run = tmp_path / "positive_run"
    changes = [
        change(path="Atlas/Dots/New Concept.md", content=created),
        change(
            path="Atlas/Dots/Existing Concept.md",
            action="UPDATE",
            content=updated,
            original_content_hash=hashlib.sha256(existing.encode()).hexdigest(),
        ),
    ]
    write_run(
        run,
        proposal(changes),
        review([
            reviewed_change("Atlas/Dots/New Concept.md"),
            reviewed_change("Atlas/Dots/Existing Concept.md"),
        ]),
    )
    vault = tmp_path / "positive_vault"
    vault.mkdir()
    write_note(vault, "Atlas/Dots/Existing Concept.md", existing)
    write_note(
        vault,
        f"Atlas/Sources/University/Machine Learning/Lectures/{lecture_title}.md",
        f"---\ntype: lecture\naliases: []\n---\n# {lecture_title}\nSource.\n",
    )
    vault_before = file_hashes(vault)
    inputs = load_reconciliation_inputs(run, vault)

    result = reconcile(inputs)
    output = stage_reconciliation(run, result, inputs)

    final = result.final_change_set
    assert final.state is FinalChangeSetState.READY_FOR_WRITE
    assert final.applicable_change_ids == ["RC-001", "RC-002"]
    assert final.human_decisions == []
    assert final.unresolved_decision_ids == []
    assert final.validation_findings == []
    assert not [item for item in final.dependencies if item.blocking]
    assert not [item for item in final.identity_collisions if item.blocking]
    dependency_states = {
        (item.source_change_id, item.normalized_target): item.target_state.value
        for item in final.dependencies
    }
    assert dependency_states[("RC-002", "new concept")] == "TARGET_CREATED_IN_BATCH"
    preview = (output / "WRITE_PREVIEW.md").read_text(encoding="utf-8")
    diff = (output / "diffs/RC-002.diff").read_text(encoding="utf-8")
    assert "State: `READY_FOR_WRITE`" in preview
    assert "2 applicable changes passed all mandatory pre-write validations." in preview
    assert "`Atlas/Dots/New Concept.md`" in preview
    assert "`Atlas/Dots/Existing Concept.md` — [diff](diffs/RC-002.diff)" in preview
    assert "+## Relationship" in diff
    assert "+The established concept now relates to [[New Concept]]" in diff
    assert file_hashes(vault) == vault_before
