from __future__ import annotations

import json
from pathlib import Path


def change(*, path: str = "Dots/Topic.md", action: str = "CREATE", content: str | None = None,
           note_type: str = "concept", original_content_hash: str | None = None) -> dict:
    return {
        "action": action,
        "note_type": note_type,
        "title": Path(path).stem,
        "target_path": path,
        "reason": "fixture",
        "content": content if content is not None else "---\ntype: concept\n---\n# Topic\nSupported body.\n",
        "sources": ["lecture.pdf"],
        "candidate_existing_notes": [],
        "original_content_hash": original_content_hash,
    }


def proposal(changes: list[dict]) -> dict:
    return {
        "workflow": "university",
        "source": "lecture.pdf",
        "source_summary": "Fixture source",
        "vault_note_count": 0,
        "note_changes": changes,
        "review_required": [],
        "source_completeness": None,
        "concept_resolutions": [],
    }


def reviewed_change(path: str, *, status: str = "PASS", issue_indices: list[int] | None = None) -> dict:
    return {"change_path": path, "status": status, "checks": [], "issue_indices": issue_indices or []}


def review(changes: list[dict], *, issues: list[dict] | None = None, overall_status: str = "PASS") -> dict:
    return {
        "overall_status": overall_status,
        "issues": issues or [],
        "reviewed_changes": changes,
        "global_review": None,
        "rejected_global_issues": [],
    }


def write_run(run: Path, reviewed_proposal: dict, review_result: dict,
              *, original_proposal: dict | None = None, agent_a_matches: bool = True) -> None:
    run.mkdir(parents=True)
    reviewed_text = json.dumps(reviewed_proposal, indent=2) + "\n"
    (run / "proposal.json").write_text(reviewed_text, encoding="utf-8")
    agent_a = run / "agent_a"
    agent_a.mkdir()
    (agent_a / "proposal.json").write_text(
        reviewed_text if agent_a_matches else json.dumps(proposal([]), indent=2) + "\n", encoding="utf-8")
    if original_proposal is not None:
        (run / "original_agent_a_proposal.json").write_text(
            json.dumps(original_proposal, indent=2) + "\n", encoding="utf-8")
    agent_b = run / "agent_b"
    agent_b.mkdir()
    (agent_b / "review.json").write_text(json.dumps(review_result, indent=2) + "\n", encoding="utf-8")


def write_note(vault: Path, path: str, content: str) -> Path:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
