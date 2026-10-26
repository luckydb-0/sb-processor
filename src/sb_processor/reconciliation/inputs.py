from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import Field

from ..knowledge.vault import scan_vault
from ..models import ProcessingProposal, ReviewResult, ReviewStatus, ScannedNote, StrictModel
from .models import PreReviewAdjustment


class ReconciliationInputs(StrictModel):
    run: Path
    vault: Path
    original_proposal: ProcessingProposal
    reviewed_proposal: ProcessingProposal
    agent_b_review: ReviewResult
    vault_notes: list[ScannedNote] = Field(default_factory=list)
    provenance: dict[str, str]
    input_sha256: dict[str, str]
    pre_review_adjustments: list[PreReviewAdjustment] = Field(default_factory=list)
    decision_input_path: Path | None = None


def resolve_vault_target(vault: Path, target: str) -> Path | None:
    """Resolve a vault-relative Markdown target without following an escape."""
    if not target or "\\" in target or not target.endswith(".md"):
        return None
    relative = PurePosixPath(target)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        return None
    root = Path(vault).resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return candidate if resolved.is_relative_to(root) else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _leaf_adjustments(before: Any, after: Any, field: str = "") -> list[PreReviewAdjustment]:
    if isinstance(before, dict) and isinstance(after, dict):
        result: list[PreReviewAdjustment] = []
        for key in sorted(before.keys() | after.keys()):
            child = f"{field}.{key}" if field else key
            if key not in before or key not in after:
                result.append(PreReviewAdjustment(field=child, before=before.get(key), after=after.get(key)))
            else:
                result.extend(_leaf_adjustments(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = []
        for index in range(max(len(before), len(after))):
            child = f"{field}[{index}]"
            if index >= len(before) or index >= len(after):
                result.append(PreReviewAdjustment(
                    field=child,
                    before=before[index] if index < len(before) else None,
                    after=after[index] if index < len(after) else None,
                ))
            else:
                result.extend(_leaf_adjustments(before[index], after[index], child))
        return result
    if before != after:
        return [PreReviewAdjustment(field=field, before=before, after=after)]
    return []


def load_reconciliation_inputs(run: Path, vault: Path) -> ReconciliationInputs:
    run = Path(run).resolve(strict=True)
    vault = Path(vault).resolve(strict=True)
    proposal_path = run / "proposal.json"
    agent_a_path = run / "agent_a" / "proposal.json"
    review_path = run / "agent_b" / "review.json"
    for required in (proposal_path, agent_a_path, review_path):
        if not required.is_file():
            raise ValueError(f"Missing reconciliation input: {required}")
    if proposal_path.read_bytes() != agent_a_path.read_bytes():
        raise ValueError("agent_a/proposal.json must be byte-identical to proposal.json")

    reviewed = ProcessingProposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))
    review = ReviewResult.model_validate_json(review_path.read_text(encoding="utf-8"))
    proposal_paths = [item.target_path for item in reviewed.note_changes]
    review_paths = [item.change_path for item in review.reviewed_changes]
    if len(proposal_paths) != len(set(proposal_paths)) or len(review_paths) != len(set(review_paths)):
        raise ValueError("Duplicate change paths prevent Agent A/Agent B alignment")
    if set(proposal_paths) != set(review_paths):
        raise ValueError("Agent B change paths do not match the reviewed Agent A proposal")
    claimed_issue_indices: set[int] = set()
    for reviewed_change in review.reviewed_changes:
        if reviewed_change.status is ReviewStatus.FIX and not reviewed_change.issue_indices:
            raise ValueError(
                f"Agent B FIX requires at least one linked issue: {reviewed_change.change_path}"
            )
        if reviewed_change.status is ReviewStatus.PASS and reviewed_change.issue_indices:
            raise ValueError(
                f"Agent B PASS cannot link correction issues: {reviewed_change.change_path}"
            )
        for issue_index in reviewed_change.issue_indices:
            if not 0 <= issue_index < len(review.issues):
                raise ValueError(
                    f"Agent B issue index is out of range for {reviewed_change.change_path}: "
                    f"{issue_index}"
                )
            if issue_index in claimed_issue_indices:
                raise ValueError(f"Agent B issue index is linked more than once: {issue_index}")
            claimed_issue_indices.add(issue_index)
            if review.issues[issue_index].change_path != reviewed_change.change_path:
                raise ValueError(
                    f"Agent B issue {issue_index} does not belong to reviewed change "
                    f"{reviewed_change.change_path}"
                )
    expected_issue_indices = set(range(len(review.issues)))
    if claimed_issue_indices != expected_issue_indices:
        orphaned = sorted(expected_issue_indices - claimed_issue_indices)
        raise ValueError(f"Agent B issues are not linked to a reviewed change: {orphaned}")
    statuses = {item.status for item in review.reviewed_changes}
    derived_status = (
        ReviewStatus.REVIEW_REQUIRED
        if ReviewStatus.REVIEW_REQUIRED in statuses
        else ReviewStatus.FIX
        if ReviewStatus.FIX in statuses
        else ReviewStatus.PASS
    )
    if review.overall_status is not derived_status:
        raise ValueError(
            "Agent B overall status does not match reviewed change statuses: "
            f"expected {derived_status.value}, got {review.overall_status.value}"
        )

    original_path = run / "original_agent_a_proposal.json"
    if original_path.is_file():
        original = ProcessingProposal.model_validate_json(original_path.read_text(encoding="utf-8"))
        original_reference = "original_agent_a_proposal.json"
    else:
        original = reviewed.model_copy(deep=True)
        original_path = proposal_path
        original_reference = "proposal.json"

    input_paths = {
        "proposal.json": proposal_path,
        "agent_a/proposal.json": agent_a_path,
        "agent_b/review.json": review_path,
    }
    if original_reference != "proposal.json":
        input_paths[original_reference] = original_path
    hashes = {name: _sha256(path) for name, path in input_paths.items()}
    adjustments = _leaf_adjustments(
        original.model_dump(mode="json"), reviewed.model_dump(mode="json")
    )
    return ReconciliationInputs(
        run=run,
        vault=vault,
        original_proposal=original,
        reviewed_proposal=reviewed,
        agent_b_review=review,
        vault_notes=scan_vault(vault),
        provenance={
            "original_agent_a_proposal": original_reference,
            "reviewed_agent_a_proposal": "proposal.json",
            "preserved_reviewed_agent_a_proposal": "agent_a/proposal.json",
            "agent_b_review": "agent_b/review.json",
        },
        input_sha256=hashes,
        pre_review_adjustments=adjustments,
    )
