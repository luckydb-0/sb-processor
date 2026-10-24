"""Mock the cloud boundary while exercising review status and evidence plumbing."""

import json
from pathlib import Path

import pytest

from sb_processor.review.runner import review_staged_run
from sb_processor.models import ReviewCheck, CheckStatus, GlobalBatchReview
from sb_processor.review.checks import required_checks

def _checks():
    return [ReviewCheck(category=category, status=CheckStatus.PASS) for category in required_checks("concept")]

from sb_processor.models import (Action, AliasAssessment, ChangeReview, NoteChange,
                                 ProcessingProposal, PromotionAssessment, ReviewIssue,
                                 ReviewStatus)


@pytest.mark.parametrize("issue_type,status,explanation", [
    ("source_independent_wording", ReviewStatus.FIX, "The lecture explains appears in the concept body"),
    ("source_fidelity", ReviewStatus.FIX, "The proposed definition lacks source support"),
    ("claim_strength", ReviewStatus.FIX, "Always is stronger than the source"),
    ("concept_boundary", ReviewStatus.REVIEW_REQUIRED, "The broad and narrow concepts may be distinct"),
])
def test_semantic_findings_have_per_change_status_and_source_evidence(
        tmp_path: Path, issue_type: str, status: ReviewStatus, explanation: str):
    vault = tmp_path / "vault"
    (vault / "+ Inbox").mkdir(parents=True)
    (vault / "+ Inbox" / "Agent B - University Processing Review Instructions.md").write_text("RULES")
    run = tmp_path / "run"
    run.mkdir()
    change = NoteChange(action=Action.CREATE, note_type="concept", title="A", target_path="Dots/A.md",
                        reason="fixture", content="---\ntype: concept\n---\n# A\nClaim", sources=[],
                        candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="missing.pdf", source_summary="A",
                                  vault_note_count=1, note_changes=[change], review_required=[])
    (run / "proposal.json").write_text(proposal.model_dump_json())
    (run / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 2]\nTEXT:\nA source statement", "relevant_existing_notes": []}))
    (run / "source_analysis.json").write_text(json.dumps({"candidate_concepts": [
        {"proposed_name": "A", "source_pages": [2]}]}))
    (run / "retrieval_evidence.json").write_text("[]")

    class Reviewer:
        def review_batch(self, request):
            return GlobalBatchReview(issues=[], summary="No cross-note findings")

        def review_change(self, request, visual_images):
            assert request.source_evidence[0].page_number == 2
            return ChangeReview(checks=_checks(), status=status, issues=[ReviewIssue(
                change_path=request.proposal_change.target_path, issue_type=issue_type,
                severity="high", explanation=explanation, proposed_correction="Correct or remove claim",
                source_pages=[2], corrected_content="---\ntype: concept\n---\n# A\nCorrected" if status == ReviewStatus.FIX else None)],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                    explanation="Independent concept", proposed_correction=""))

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == status
    assert result.issues[0].source_pages == [2]
    if status == ReviewStatus.FIX:
        assert (run / "agent_b" / "corrected_notes" / "Dots" / "A.md").exists()
    else:
        assert not (run / "agent_b" / "corrected_notes").exists()
    assert change.content == ProcessingProposal.model_validate_json((run / "proposal.json").read_text()).note_changes[0].content
