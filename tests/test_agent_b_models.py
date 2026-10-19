from pydantic import ValidationError
import pytest

from sb_processor.models import ReviewIssue, ReviewedChange, ReviewResult, ReviewStatus


def test_review_result_requires_per_change_structured_findings():
    issue = ReviewIssue(change_path="Dots/A.md", issue_type="source_fidelity", severity="high",
                        explanation="Unsupported claim", proposed_correction="Remove claim",
                        source_pages=[2])
    result = ReviewResult(overall_status=ReviewStatus.FIX, issues=[issue],
                          reviewed_changes=[ReviewedChange(change_path="Dots/A.md", status=ReviewStatus.FIX,
                                                           issue_indices=[0])])
    assert result.reviewed_changes[0].status == ReviewStatus.FIX
    assert result.issues[0].source_pages == [2]
    with pytest.raises(ValidationError):
        ReviewResult(overall_status="MAYBE", issues=[], reviewed_changes=[])
