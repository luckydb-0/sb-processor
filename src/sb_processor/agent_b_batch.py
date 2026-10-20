"""Lean cross-note review and deterministic grouping for human review."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import Field

from .models import GlobalBatchReview, ProcessingProposal, ReviewIssue, ReviewResult, ReviewStatus, StrictModel


class BatchReviewRequest(StrictModel):
    workflow: str
    source_summary: str
    changes: list[dict]
    individual_issues: list[dict]
    systematic_patterns: list[dict] = Field(default_factory=list)
    equivalence: list[dict] = Field(default_factory=list)
    instructions: str


def build_batch_request(proposal: ProcessingProposal, result: ReviewResult) -> BatchReviewRequest:
    by_path = {item.change_path: item for item in result.reviewed_changes}
    return BatchReviewRequest(
        workflow=proposal.workflow,
        source_summary=proposal.source_summary[:1200],
        changes=[{
            "path": change.target_path, "title": change.title, "type": change.note_type,
            "action": change.action.value, "status": by_path[change.target_path].status.value,
            "checks": {check.category.value: check.status.value for check in by_path[change.target_path].checks},
        } for change in proposal.note_changes],
        individual_issues=[{"index": index, "path": issue.change_path, "type": issue.issue_type.value,
                            "explanation": issue.explanation[:150],
                            "source_pages": sorted(set(issue.source_pages + [ref.page for ref in issue.evidence_refs
                                                                           if ref.page is not None])),
                            "existing_note_refs": [ref.note_path for ref in issue.evidence_refs
                                                   if ref.note_path and ref.note_path.endswith(".md")][:2]}
                           for index, issue in enumerate(result.issues)],
        systematic_patterns=[{"type": item["issue_type"], "root": item["root"],
                              "count": item["count"], "affected_paths": item["affected_paths"]}
                             for item in systematic_issue_groups(result.issues)],
        equivalence=[{"candidate": item.candidate_name, "relation": item.relation.value,
                      "existing_path": item.existing_path} for item in proposal.concept_resolutions],
        instructions=("Inspect batch-level duplicate concepts, inconsistent naming/aliases/boundaries, "
                      "systematic provenance or source wording mistakes, Dot proliferation, Map/Course/Lecture "
                      "relationships, and repeated issues. Use only the summaries and supplied issue evidence. "
                      "Do not infer source facts or invent corrections. Cite supporting_issue_indices. "
                      "Return only cross-note patterns or decisions; no duplicate per-note issue list."),
    )


def validate_batch_review(batch: GlobalBatchReview, request: BatchReviewRequest) -> None:
    paths = {item["path"] for item in request.changes}
    indices = {item["index"] for item in request.individual_issues}
    for issue in batch.issues:
        if not issue.affected_paths or not set(issue.affected_paths) <= paths:
            raise ValueError("Global review referenced an unknown or empty affected path set")
        if not set(issue.supporting_issue_indices) <= indices:
            raise ValueError("Global review referenced unknown individual issues")


def filter_unsupported_batch_issues(batch: GlobalBatchReview, request: BatchReviewRequest):
    """Keep only cross-note claims that cite matching individual findings."""
    paths = {item["path"] for item in request.changes}
    by_index = {item["index"]: item for item in request.individual_issues}
    relevant_types = {
        "duplicate_concept": {"duplicate_concept", "concept_boundary"},
        "concept_boundaries": {"concept_boundary", "duplicate_concept"},
        "source_fidelity": {"source_fidelity", "claim_strength"},
        "provenance": {"provenance"},
        "source_independence": {"source_independent_wording"},
        "aliases": {"alias"},
        "dot_promotion": {"dot_promotion"},
        "links": {"link"},
        "naming": {"naming"},
        "cumulative_integrity": {"cumulative_integrity", "existing_note", "duplicate_concept"},
    }
    accepted, rejected = [], []
    for issue in batch.issues:
        support = [by_index[index] for index in issue.supporting_issue_indices if index in by_index]
        valid = (len(set(issue.affected_paths)) >= 2 and set(issue.affected_paths) <= paths
                 and len(support) == len(issue.supporting_issue_indices)
                 and len({item["path"] for item in support}) >= 2
                 and all(item["path"] in issue.affected_paths for item in support)
                 and any(item["path"] in issue.affected_paths and
                         item["type"] in relevant_types.get(issue.category.value, {issue.category.value})
                         for item in support))
        if issue.category.value not in {"provenance", "links", "workflow_contamination", "naming"}:
            relevant_paths = {item["path"] for item in support
                              if item["type"] in relevant_types.get(issue.category.value, {issue.category.value})}
            valid = valid and set(issue.affected_paths) <= relevant_paths
        if issue.category.value == "duplicate_concept" and issue.status.value == "FIX":
            issue.status = ReviewStatus.REVIEW_REQUIRED
        if valid:
            accepted.append(issue)
        else:
            rejected.append(issue)
    return GlobalBatchReview(issues=accepted, summary=batch.summary), rejected


def _root_key(issue: ReviewIssue) -> tuple[str, str]:
    explanation = issue.explanation
    if issue.issue_type.value == "link":
        match = re.search(r"\[\[([^\]]+)\]\]", explanation)
        if match:
            return "link", match.group(1).casefold()
    if issue.issue_type.value == "provenance" and "PDF metadata" in explanation:
        return "provenance", "direct PDF metadata"
    if issue.issue_type.value == "naming" and "Map filename collides" in explanation:
        return "naming", "Map filename collision"
    return issue.issue_type.value, explanation.casefold()


def systematic_issue_groups(issues: list[ReviewIssue]) -> list[dict]:
    groups: dict[tuple[str, str], list[tuple[int, ReviewIssue]]] = defaultdict(list)
    for index, issue in enumerate(issues):
        groups[_root_key(issue)].append((index, issue))
    output = []
    for (kind, root), members in groups.items():
        paths = sorted({issue.change_path for _, issue in members})
        if len(paths) < 2:
            continue
        output.append({"issue_type": kind, "root": root, "affected_paths": paths,
                       "count": len(paths), "issue_indices": [index for index, _ in members],
                       "recommendation": members[0][1].proposed_correction})
    return sorted(output, key=lambda item: (-item["count"], item["root"]))
