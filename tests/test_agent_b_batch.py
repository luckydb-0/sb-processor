from sb_processor.agent_b_batch import systematic_issue_groups, build_batch_request, validate_batch_review
from sb_processor.models import (Action, CheckStatus, GlobalBatchReview, GlobalReviewIssue, NoteChange,
                                 ProcessingProposal, ReviewCheck, ReviewIssue, ReviewedChange,
                                 ReviewResult, ReviewStatus)
from sb_processor.review_checks import required_checks


def test_identical_ghost_links_group_into_one_human_issue():
    issues = [ReviewIssue(change_path=f"Dots/Note {index}.md", issue_type="link", severity="medium",
                          explanation="Unresolved wikilink: [[Machine Learning - Map]]",
                          proposed_correction="Use canonical Map target") for index in range(14)]
    groups = systematic_issue_groups(issues)
    assert len(groups) == 1
    assert groups[0]["count"] == 14
    assert groups[0]["root"] == "machine learning - map"


def test_batch_request_contains_summaries_without_source_pages():
    changes = [NoteChange(action=Action.CREATE, note_type="concept", title="A", target_path="Dots/A.md",
                          reason="fixture", content="SOURCE SECRET SHOULD NOT GO TO GLOBAL REVIEW", sources=[],
                          candidate_existing_notes=[], original_content_hash=None)]
    proposal = ProcessingProposal(workflow="university", source="source.pdf", source_summary="Topic A",
                                  vault_note_count=0, note_changes=changes, review_required=[])
    result = ReviewResult(overall_status=ReviewStatus.PASS, issues=[], reviewed_changes=[ReviewedChange(
        change_path="Dots/A.md", status=ReviewStatus.PASS,
        checks=[ReviewCheck(category=item, status=CheckStatus.PASS) for item in required_checks("concept")])])
    request = build_batch_request(proposal, result)
    assert "SOURCE SECRET" not in request.model_dump_json()
    assert request.changes[0]["title"] == "A"
    validate_batch_review(GlobalBatchReview(issues=[], summary="None"), request)


def test_global_review_rejects_unknown_affected_path():
    change = NoteChange(action=Action.CREATE, note_type="concept", title="A", target_path="Dots/A.md",
                        reason="fixture", content="# A", sources=[], candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="source.pdf", source_summary="A",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    result = ReviewResult(overall_status=ReviewStatus.PASS, issues=[], reviewed_changes=[ReviewedChange(
        change_path="Dots/A.md", status=ReviewStatus.PASS,
        checks=[ReviewCheck(category=item, status=CheckStatus.PASS) for item in required_checks("concept")])])
    request = build_batch_request(proposal, result)
    batch = GlobalBatchReview(issues=[GlobalReviewIssue(category="duplicate_concept", status="REVIEW_REQUIRED",
        affected_paths=["Dots/Invented.md"], explanation="Maybe duplicate", recommendation="Review")], summary="")
    import pytest
    with pytest.raises(ValueError, match="unknown"):
        validate_batch_review(batch, request)
