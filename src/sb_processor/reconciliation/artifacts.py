from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from ..models import Action
from .inputs import ReconciliationInputs
from .inputs import load_reconciliation_inputs, resolve_vault_target
from .engine import reconcile
from .models import (
    DecisionStatus,
    ReconciledChangeStatus,
    ReconciliationResult,
    FinalChangeSet,
)


def _verify_inputs(inputs: ReconciliationInputs) -> None:
    for relative, expected in inputs.input_sha256.items():
        path = (inputs.decision_input_path
                if relative == "human_decisions.json" else inputs.run / relative)
        if path is None or not path.is_file():
            raise ValueError(f"Reconciliation input is missing during processing: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Reconciliation input changed during processing: {relative}")


def _verify_vault_snapshot(result: ReconciliationResult, inputs: ReconciliationInputs) -> None:
    for change in result.final_change_set.changes:
        if change.final_action is not Action.UPDATE:
            continue
        expected = change.expected_existing_content_sha256
        if expected is None:
            continue
        relative = change.final_target_path or change.original_target_path
        target = resolve_vault_target(inputs.vault, relative)
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target and target.is_file() else None
        if actual != expected:
            raise ValueError(f"Vault UPDATE target changed during reconciliation: {relative}")


def _human_review(result: ReconciliationResult) -> str:
    final = result.final_change_set
    change_by_id = {item.id: item for item in final.changes}
    ready = sum(item.status is ReconciledChangeStatus.READY for item in final.changes)
    fixed = sum(item.status is ReconciledChangeStatus.FIXED for item in final.changes)
    pending_decisions = [item for item in final.human_decisions
                         if item.status is DecisionStatus.PENDING]
    pending = len(pending_decisions)
    resolved = len(final.human_decisions) - pending
    lines = [
        "# Human Review",
        "",
        "## Summary",
        "",
        f"Automatically ready: {ready}",
        f"Automatically fixed: {fixed}",
        f"Needs your decision: {pending}",
        f"Resolved or deferred decisions: {resolved}",
        "",
        f"FinalChangeSet: `{final.state.value}`",
        "",
        "## Decisions",
        "",
    ]
    if not final.human_decisions:
        lines.extend(["No human decisions are required.", ""])
    elif not pending_decisions:
        lines.extend([
            "No pending human decisions. See `human_decisions.json` for the complete audit.",
            "",
        ])
    for decision in pending_decisions:
        lines.extend([
            f"### {decision.id} — {decision.category}",
            "",
            f"**Status:** `{decision.status.value}`",
            "",
            f"**Blocking:** `{'yes' if decision.blocking else 'no'}`",
            "",
            "**Affected changes**",
            "",
            *[
                f"- `{change_by_id[change_id].final_target_path or change_by_id[change_id].original_target_path}`"
                for change_id in decision.change_ids
            ],
            "",
            "**Question**",
            "",
            decision.question,
            "",
            "**Agent A**",
            "",
            decision.agent_a_position,
            "",
            "**Agent B**",
            "",
            decision.agent_b_position,
            "",
            "**Evidence**",
            "",
            decision.context,
            "",
        ])
        if decision.recommendation:
            lines.extend([
                "**Recommendation**",
                "",
                f"`{decision.recommendation}` — {decision.rationale or ''}".rstrip(),
                "",
            ])
        lines.extend(["**Options**", ""])
        for option in decision.options:
            consequence = f" Consequence: {option.consequence}" if option.consequence else ""
            lines.append(f"- `{option.key}` — {option.label}.{consequence}")
        if decision.selected_option:
            lines.extend(["", f"**Selected:** `{decision.selected_option}`"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_diff(root: Path, inputs: ReconciliationInputs, change) -> str:
    path = change.final_target_path or change.original_target_path
    target = resolve_vault_target(inputs.vault, path)
    if target is None:
        raise ValueError(f"Unsafe UPDATE target path: {path}")
    before = target.read_text(encoding="utf-8").splitlines(keepends=True)
    after = (change.final_content or "").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(
        before,
        after,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    relative = f"diffs/{change.id}.diff"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(diff, encoding="utf-8")
    return relative


def _write_preview(root: Path, result: ReconciliationResult, inputs: ReconciliationInputs) -> str:
    final = result.final_change_set
    dependency_groups: dict[tuple[str, str, str | None, str | None], list] = {}
    for dependency in final.dependencies:
        key = (
            dependency.normalized_target,
            dependency.target_state.value,
            dependency.target_path,
            dependency.root_decision_id,
        )
        dependency_groups.setdefault(key, []).append(dependency)
    groups: dict[str, list[str]] = {
        "CREATE": [],
        "UPDATE": [],
        "UNCHANGED": [],
        "SKIPPED": [],
        "BLOCKED": [],
        "DEFERRED": [],
        "INVALID": [],
    }
    for change in final.changes:
        path = change.final_target_path or change.original_target_path
        if change.status is ReconciledChangeStatus.BLOCKED:
            pending = [item for item in change.human_decision_ids
                       if item in final.unresolved_decision_ids]
            suffix = f" — {', '.join(pending)} pending" if pending else ""
            groups["BLOCKED"].append(f"- `{path}`{suffix}")
        elif change.status is ReconciledChangeStatus.DEFERRED:
            groups["DEFERRED"].append(f"- `{path}`")
        elif change.status is ReconciledChangeStatus.SKIPPED:
            groups["SKIPPED"].append(f"- `{path}`")
        elif change.status is ReconciledChangeStatus.INVALID:
            groups["INVALID"].append(f"- `{path}`")
        elif change.final_action is Action.UPDATE:
            relative = _write_diff(root, inputs, change)
            groups["UPDATE"].append(f"- `{path}` — [diff]({relative})")
        elif change.final_action is Action.CREATE:
            groups["CREATE"].append(f"- `{path}`")
        else:
            groups["UNCHANGED"].append(f"- `{path}`")
    lines = ["# Write Preview", "", f"State: `{final.state.value}`", "",
             "No vault files were written.", ""]
    for name in (
        "CREATE", "UPDATE", "UNCHANGED", "SKIPPED", "DEFERRED", "BLOCKED", "INVALID"
    ):
        lines.extend([f"## {name}", ""])
        lines.extend(groups[name] or ["None."])
        lines.append("")
    lines.extend(["## Accepted risks", ""])
    if final.accepted_risks:
        for risk in final.accepted_risks:
            applies = any(
                change_id in final.applicable_change_ids for change_id in risk.change_ids
            )
            scope = "" if applies else " (affected changes are excluded from the applicable subset)"
            lines.append(
                f"- `{risk.id}` authorized by `{risk.decision_id}` — "
                f"{risk.description}{scope}"
            )
            if risk.material_loss_ids:
                lines.append(
                    "  - Losses: " + ", ".join(f"`{item}`" for item in risk.material_loss_ids)
                )
            for evidence in risk.evidence:
                lines.append(f"  - Evidence: {evidence}")
    else:
        lines.append("None.")
    lines.extend(["", "## Blocking issues", ""])
    blocking: list[str] = []
    for decision in final.human_decisions:
        if decision.blocking and decision.status is DecisionStatus.PENDING:
            blocking.append(f"- `{decision.id}` — {decision.question}")
    for collision in final.identity_collisions:
        if collision.blocking:
            blocking.append(
                f"- `{collision.id}` — ambiguous identity `{collision.normalized_identity}`"
            )
    for (normalized, state, target_path, root_id), records in dependency_groups.items():
        if records[0].blocking:
            sources = sorted({item.source_path for item in records})
            occurrence = "occurrence" if len(records) == 1 else "occurrences"
            blocking.append(
                f"- Dependency `{records[0].token}` (`{normalized}`): `{state}` — "
                f"{len(records)} {occurrence} "
                f"across {len(sources)} change(s)"
                + (f"; target `{target_path}`" if target_path else "")
                + (f"; root decision `{root_id}`" if root_id else "")
            )
    for change in final.changes:
        for loss in change.material_losses:
            if (loss.disposition.value == "ISSUE_UNRESOLVED"
                    and loss.decision_id in final.unresolved_decision_ids):
                blocking.append(
                    f"- `{loss.id}` — unacknowledged {loss.kind.value.lower()} loss in "
                    f"`{change.final_target_path or change.original_target_path}`"
                )
    lines.extend(blocking or ["None."])
    lines.extend(["", "## Dependencies", ""])
    if dependency_groups:
        for (normalized, state, target_path, root_id), records in dependency_groups.items():
            sources = sorted({item.source_path for item in records})
            target = f"; target `{target_path}`" if target_path else ""
            root_decision = f"; root decision `{root_id}`" if root_id else ""
            occurrence = "occurrence" if len(records) == 1 else "occurrences"
            lines.append(
                f"- `{records[0].token}` (`{normalized}`) → `{state}` — "
                f"{len(records)} {occurrence} across "
                f"{len(sources)} change(s){target}{root_decision}"
            )
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def stage_reconciliation(run: Path, result: ReconciliationResult,
                         inputs: ReconciliationInputs) -> Path:
    """Render one complete reconciliation directory and replace only prior generated output."""
    run = Path(run).resolve(strict=True)
    if run != inputs.run:
        raise ValueError("Staging run does not match loaded reconciliation inputs")
    _verify_inputs(inputs)
    _verify_vault_snapshot(result, inputs)
    temporary = Path(tempfile.mkdtemp(prefix=".reconciliation-", dir=run))
    try:
        final = result.final_change_set
        (temporary / "reconciliation.json").write_text(
            result.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (temporary / "final_change_set.json").write_text(
            final.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        decision_payload = {
            "source_run_id": final.source_run_id,
            "decisions": [item.model_dump(mode="json") for item in final.human_decisions],
        }
        (temporary / "human_decisions.json").write_text(
            json.dumps(decision_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (temporary / "HUMAN_REVIEW.md").write_text(_human_review(result), encoding="utf-8")
        (temporary / "WRITE_PREVIEW.md").write_text(
            _write_preview(temporary, result, inputs), encoding="utf-8"
        )
        _verify_inputs(inputs)
        _verify_vault_snapshot(result, inputs)
        output = run / "reconciliation"
        if output.exists():
            shutil.rmtree(output)
        temporary.replace(output)
        return output
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _load_decisions(path: Path | None) -> tuple[dict[str, str], Path | None, str | None]:
    if path is None:
        return {}, None, None
    resolved = Path(path).resolve(strict=True)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                            for key, value in payload.items()):
        raise ValueError("Decision file must contain a JSON object mapping decision IDs to option keys")
    return payload, resolved, hashlib.sha256(raw).hexdigest()


def run_reconciliation(run: Path, vault: Path,
                       decisions_path: Path | None = None) -> FinalChangeSet:
    inputs = load_reconciliation_inputs(run, vault)
    selections, resolved_decisions, decisions_sha256 = _load_decisions(decisions_path)
    if resolved_decisions is not None:
        if resolved_decisions.is_relative_to(inputs.run / "reconciliation"):
            raise ValueError("Decision file must be outside the generated reconciliation directory")
        inputs.decision_input_path = resolved_decisions
        inputs.provenance["human_decisions"] = str(resolved_decisions)
        assert decisions_sha256 is not None
        inputs.input_sha256["human_decisions.json"] = decisions_sha256
    result = reconcile(inputs, selections)
    stage_reconciliation(inputs.run, result, inputs)
    return result.final_change_set
