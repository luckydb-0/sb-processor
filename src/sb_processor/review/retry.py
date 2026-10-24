"""One bounded retry for mandatory checks that lack actionable evidence."""

from __future__ import annotations

from pydantic import Field

from .context import AgentBRequest
from ..models import (ChangeReview, CheckStatus, ReviewCategory, ReviewCheck,
                      ReviewIssue, ReviewStatus, StrictModel)


ISSUE_CATEGORY = {
    "source_independent_wording": ReviewCategory.SOURCE_INDEPENDENCE,
    "source_specific_result": ReviewCategory.SOURCE_SPECIFIC_RESULTS,
    "existing_note": ReviewCategory.EXISTING_NOTE_INTEGRITY,
    "concept_boundary": ReviewCategory.CONCEPT_BOUNDARIES,
    "duplicate_concept": ReviewCategory.DUPLICATE_CONCEPT,
    "dot_promotion": ReviewCategory.DOT_PROMOTION,
    "alias": ReviewCategory.ALIASES,
    "link": ReviewCategory.LINKS,
    "map": ReviewCategory.MAP_STRUCTURE,
    "course": ReviewCategory.COURSE_STRUCTURE,
    "lecture": ReviewCategory.LECTURE_STRUCTURE,
    "verbosity": ReviewCategory.SYNTHESIS,
}


def issue_category(issue: ReviewIssue) -> ReviewCategory | None:
    return ISSUE_CATEGORY.get(issue.issue_type.value) or ReviewCategory._value2member_map_.get(issue.issue_type.value)


def valid_issue_evidence(issue: ReviewIssue, request: AgentBRequest) -> bool:
    """Citations must point to supplied evidence, not to an invented page or note."""
    if issue.change_path != request.proposal_change.target_path:
        return False
    pages = {page.page_number for page in request.source_evidence}
    note_paths = {request.proposal_change.target_path,
                  *(note.path for note in request.affected_existing_notes)}
    cited_pages = set(issue.source_pages) | {ref.page for ref in issue.evidence_refs if ref.page is not None}
    if cited_pages - pages:
        return False
    if any(ref.note_path and ref.note_path not in note_paths for ref in issue.evidence_refs):
        return False
    if issue_category(issue) in {ReviewCategory.SOURCE_FIDELITY, ReviewCategory.CLAIM_STRENGTH,
                                 ReviewCategory.SOURCE_SPECIFIC_RESULTS}:
        return bool(cited_pages)
    return bool(cited_pages or any(ref.note_path in note_paths for ref in issue.evidence_refs))


def unsupported_failures(request: AgentBRequest, response: ChangeReview) -> list[ReviewCategory]:
    objective_categories = {issue_category(ReviewIssue.model_validate(item))
                            for item in request.deterministic_findings}
    return [check.category for check in response.checks if check.status == CheckStatus.FAIL
            and check.category not in objective_categories and not any(
        issue_category(issue) == check.category and valid_issue_evidence(issue, request)
        for issue in response.issues)]


class TargetedRetryRequest(StrictModel):
    review_context: AgentBRequest
    categories: list[ReviewCategory]
    previous_checks: list[ReviewCheck]
    previous_issues: list[ReviewIssue]
    instruction: str = (
        "Re-evaluate ONLY categories. The first FAIL lacked a concrete issue with valid supplied evidence. "
        "PASS if no supported problem exists; FAIL only with a concrete issue and valid citation; "
        "INSUFFICIENT_EVIDENCE when evidence cannot resolve the check. Use proposed_final_content as the "
        "review target and existing_content only for update-integrity comparisons. Detecting a problem does "
        "NOT grant permission to add missing knowledge. Use no external facts or examples."
    )


class TargetedRetryResult(StrictModel):
    checks: list[ReviewCheck]
    issues: list[ReviewIssue] = Field(default_factory=list)
    status: ReviewStatus


def make_retry_request(request: AgentBRequest, response: ChangeReview,
                       categories: list[ReviewCategory]) -> TargetedRetryRequest:
    return TargetedRetryRequest(review_context=request, categories=categories,
        previous_checks=[check for check in response.checks if check.category in categories],
        previous_issues=[issue for issue in response.issues if issue_category(issue) in categories])


def reconcile_retry(request: AgentBRequest, response: ChangeReview, retry_request: TargetedRetryRequest,
                    retry_result: TargetedRetryResult) -> dict:
    expected = set(retry_request.categories)
    actual = [check.category for check in retry_result.checks]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Targeted Agent B retry returned missing, extra, or duplicate check categories")
    retained = [issue for issue in response.issues if issue_category(issue) not in expected]
    recovered: list[ReviewIssue] = []
    final_checks: dict[ReviewCategory, ReviewCheck] = {}
    for check in retry_result.checks:
        matching = [issue for issue in retry_result.issues if issue_category(issue) == check.category
                    and valid_issue_evidence(issue, request)]
        if check.status == CheckStatus.FAIL and not matching:
            check = check.model_copy(update={"status": CheckStatus.INSUFFICIENT_EVIDENCE,
                "explanation": "Retry did not substantiate this failure with supplied evidence"})
        if check.status == CheckStatus.FAIL:
            recovered.extend(matching)
        final_checks[check.category] = check
    response.checks = [final_checks.get(check.category, check) for check in response.checks]
    response.issues = [*retained, *recovered]
    if not retained:
        response.status = (ReviewStatus.REVIEW_REQUIRED if recovered and retry_result.status == ReviewStatus.REVIEW_REQUIRED
                           else ReviewStatus.FIX if recovered else ReviewStatus.PASS)
    elif recovered and retry_result.status == ReviewStatus.REVIEW_REQUIRED:
        response.status = ReviewStatus.REVIEW_REQUIRED
    return {
        "change_path": request.proposal_change.target_path,
        "initial_failed_checks": [check.category.value for check in retry_request.previous_checks],
        "checks_retried": [category.value for category in retry_request.categories],
        "retry_result": {category.value: check.status.value for category, check in final_checks.items()},
        "issues_recovered": len(recovered),
        "changed_to_pass": sum(check.status == CheckStatus.PASS for check in final_checks.values()),
        "changed_to_insufficient_evidence": sum(check.status == CheckStatus.INSUFFICIENT_EVIDENCE
                                                for check in final_checks.values()),
        "retry_request_chars": len(retry_request.model_dump_json()),
        "visual_pages_reused": [number for number in {page.page_number for page in request.source_evidence}
                                if any(item.get("page_number") == number for item in request.visual_evidence)],
        "blocking_uncertainty": [check.category.value for check in final_checks.values()
                                  if check.status == CheckStatus.INSUFFICIENT_EVIDENCE
                                  and check.category in {ReviewCategory.CONCEPT_BOUNDARIES,
                                                         ReviewCategory.DUPLICATE_CONCEPT,
                                                         ReviewCategory.DOT_PROMOTION,
                                                         ReviewCategory.EXISTING_NOTE_INTEGRITY,
                                                         ReviewCategory.CUMULATIVE_INTEGRITY}
                                  and retry_result.status == ReviewStatus.REVIEW_REQUIRED],
    }
