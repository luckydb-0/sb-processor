from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from ..models import Action
from .inputs import ReconciliationInputs
from .inputs import load_reconciliation_inputs
from .engine import reconcile
from .models import (
    DecisionStatus,
    ReconciledChangeStatus,
    ReconciliationResult,
    FinalChangeSet,
)


def _verify_inputs(inputs: ReconciliationInputs) -> None:
    for relative, expected in inputs.input_sha256.items():
        path = inputs.run / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Reconciliation input changed during processing: {relative}")


def _human_review(result: ReconciliationResult) -> str:
    final = result.final_change_set
    ready = sum(item.status is ReconciledChangeStatus.READY for item in final.changes)
    fixed = sum(item.status is ReconciledChangeStatus.FIXED for item in final.changes)
    pending = sum(item.status is DecisionStatus.PENDING for item in final.human_decisions)
    lines = [
        "# Human Review",
        "",
        "## Summary",
        "",
        f"Automatically ready: {ready}",
        f"Automatically fixed: {fixed}",
        f"Needs your decision: {pending}",
        "",
        f"FinalChangeSet: `{final.state.value}`",
        "",
        "## Decisions",
        "",
    ]
    if not final.human_decisions:
        lines.extend(["No human decisions are required.", ""])
    for decision in final.human_decisions:
        lines.extend([
            f"### {decision.id} — {decision.category}",
            "",
            f"**Status:** `{decision.status.value}`",
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
            lines.append(f"- `{option.key}` — {option.label}")
        if decision.selected_option:
            lines.extend(["", f"**Selected:** `{decision.selected_option}`"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_diff(root: Path, inputs: ReconciliationInputs, change) -> str:
    path = change.final_target_path or change.original_target_path
    before = (inputs.vault / path).read_text(encoding="utf-8").splitlines(keepends=True)
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
    groups: dict[str, list[str]] = {
        "CREATE": [],
        "UPDATE": [],
        "NO_CHANGE": [],
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
        elif change.status is ReconciledChangeStatus.INVALID:
            groups["INVALID"].append(f"- `{path}`")
        elif change.final_action is Action.UPDATE:
            relative = _write_diff(root, inputs, change)
            groups["UPDATE"].append(f"- `{path}` — [diff]({relative})")
        elif change.final_action is Action.CREATE:
            groups["CREATE"].append(f"- `{path}`")
        else:
            groups["NO_CHANGE"].append(f"- `{path}`")
    lines = ["# Write Preview", "", f"State: `{final.state.value}`", "",
             "No vault files were written.", ""]
    for name in ("CREATE", "UPDATE", "NO_CHANGE", "BLOCKED", "DEFERRED", "INVALID"):
        lines.extend([f"## {name}", ""])
        lines.extend(groups[name] or ["None."])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def stage_reconciliation(run: Path, result: ReconciliationResult,
                         inputs: ReconciliationInputs) -> Path:
    """Render one complete reconciliation directory and replace only prior generated output."""
    run = Path(run).resolve(strict=True)
    if run != inputs.run:
        raise ValueError("Staging run does not match loaded reconciliation inputs")
    _verify_inputs(inputs)
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
        output = run / "reconciliation"
        if output.exists():
            shutil.rmtree(output)
        temporary.replace(output)
        return output
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _load_decisions(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                            for key, value in payload.items()):
        raise ValueError("Decision file must contain a JSON object mapping decision IDs to option keys")
    return payload


def run_reconciliation(run: Path, vault: Path,
                       decisions_path: Path | None = None) -> FinalChangeSet:
    inputs = load_reconciliation_inputs(run, vault)
    result = reconcile(inputs, _load_decisions(decisions_path))
    stage_reconciliation(inputs.run, result, inputs)
    return result.final_change_set
