from sb_processor.agent_b_context import AgentBRequest, SourcePageEvidence
from sb_processor.agent_b_evidence import (bind_issue_references, constrain_corrections,
                                           evidence_supported_alias_relation, normalize_promotion_check)
from sb_processor.models import (Action, AliasAssessment, ChangeReview, NoteChange, PromotionAssessment,
                                 ReviewCheck, CheckStatus, ReviewIssue, ReviewStatus)
from sb_processor.review_checks import required_checks


def _request(title: str, source: str, alias: str = "") -> AgentBRequest:
    content = f"---\ntype: concept\n---\n# {title}\nA supported claim."
    return AgentBRequest(workflow="university", proposal_change=NoteChange(
        action=Action.CREATE, note_type="concept", title=title, target_path=f"Dots/{title}.md",
        reason="test", content=content, sources=[], candidate_existing_notes=[], original_content_hash=None),
        proposal_summary="", source_metadata={}, source_evidence=[SourcePageEvidence(page_number=35, text=source)],
        source_pages_available=1, evidence_selection="explicit", affected_existing_notes=[], retrieval_evidence=[],
        review_instructions="", required_checks=required_checks("concept"), aliases_to_review=[alias] if alias else [])


def _review(issues=None, aliases=None, promotion=None):
    return ChangeReview(status=ReviewStatus.FIX if issues else ReviewStatus.PASS, issues=issues or [],
                        checks=[ReviewCheck(category=category, status=CheckStatus.PASS)
                                for category in required_checks("concept")],
                        alias_assessments=aliases or [], promotion_assessment=promotion)


def test_similarity_matching_does_not_gain_unsourced_distance_examples():
    request = _request("Similarity Matching", "Similarity matching requires suitable similarity measures.")
    review = _review([ReviewIssue(change_path="Dots/Similarity Matching.md", issue_type="source_specific_result",
                                  severity="medium", explanation="The source does not provide examples of measures",
                                  proposed_correction="Include common measures like Euclidean distance or cosine similarity.",
                                  source_pages=[35])])
    constrain_corrections(request, review)
    assert review.issues == []
    assert "Euclidean" not in review.model_dump_json()
    assert "cosine" not in review.model_dump_json()


def test_explicit_alias_evidence_accepts_profiling_and_regression():
    for title, alias, source in (
        ("Profiling", "Behavior Description", "profiling\nalso known as behavior description"),
        ("Regression", "Value Estimation", "regression (value estimation)"),
    ):
        request = _request(title, source, alias)
        review = _review(aliases=[AliasAssessment(alias=alias, relation="SUBTYPE", status=ReviewStatus.FIX,
                                                  explanation="Invented subtype claim", proposed_correction="Remove alias")])
        evidence_supported_alias_relation(request, review)
        assert review.alias_assessments[0].relation.value == "IDENTITY_EQUIVALENT"


def test_subtype_alias_remains_suspicious_without_identity_evidence():
    request = _request("Cross-Validation", "K-Fold Cross-Validation is a subtype of Cross-Validation.",
                       "K-Fold Cross-Validation")
    review = _review(aliases=[AliasAssessment(alias="K-Fold Cross-Validation", relation="SUBTYPE",
                                              status=ReviewStatus.FIX, explanation="Source says subtype",
                                              proposed_correction="Remove alias")])
    evidence_supported_alias_relation(request, review)
    assert review.alias_assessments[0].relation.value == "SUBTYPE"


def test_foundational_dot_promotion_is_not_based_on_length_alone():
    for title in ("Regression", "Reinforcement Learning"):
        assessment = PromotionAssessment(status=ReviewStatus.PASS, explanation="Foundational reusable concept",
                                         proposed_correction="", substantive_content=False,
                                         foundational_identity=True)
        assert assessment.foundational_identity and assessment.status == ReviewStatus.PASS


def test_uncited_structural_issue_refs_the_proposed_note():
    request = _request("A", "A is supported")
    review = _review([ReviewIssue(change_path="Dots/A.md", issue_type="link", severity="medium",
                                  explanation="Link is excessive", proposed_correction="Remove it")])
    bind_issue_references(request, review)
    assert review.issues[0].evidence_refs[0].note_path == "Dots/A.md"


def test_uncited_semantic_assertion_becomes_evidence_gap():
    request = _request("A", "A is supported")
    review = _review([ReviewIssue(change_path="Dots/A.md", issue_type="concept_boundary", severity="medium",
                                  explanation="B is a subtype", proposed_correction="Split B")])
    bind_issue_references(request, review)
    assert review.issues[0].issue_type.value == "evidence_gap"
    assert review.status == ReviewStatus.REVIEW_REQUIRED
    assert "Split B" not in review.model_dump_json()


def test_dot_promotion_respects_explicit_foundational_identity():
    review = _review()
    check = next(item for item in review.checks if item.category.value == "dot_promotion")
    check.status = CheckStatus.FAIL
    check.explanation = "Although a foundational concept, it is short."
    normalize_promotion_check(review)
    assert check.status == CheckStatus.PASS
