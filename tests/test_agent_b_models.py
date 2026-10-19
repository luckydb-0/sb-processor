from pydantic import ValidationError
import pytest

from sb_processor.models import (AliasAssessment, ChangeReview, PromotionAssessment,
                                 ReviewIssue, ReviewedChange, ReviewResult, ReviewStatus)


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
    with pytest.raises(ValidationError):
        ReviewIssue(change_path="Dots/A.md", issue_type="invented_category", severity="high",
                    explanation="x", proposed_correction="y")


def test_change_review_records_alias_and_promotion_decisions():
    review = ChangeReview(status=ReviewStatus.FIX, issues=[], alias_assessments=[
        AliasAssessment(alias="K-Fold Cross-Validation", status=ReviewStatus.FIX,
                        relation="SUBTYPE", explanation="Subtype", proposed_correction="Remove alias")],
        promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                                                 explanation="Independent concept", proposed_correction=""))
    assert review.alias_assessments[0].status == ReviewStatus.FIX
    assert review.promotion_assessment.status == ReviewStatus.PASS
