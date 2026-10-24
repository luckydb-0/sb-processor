from types import SimpleNamespace

from sb_processor.models import Action, ChangeReview, CheckStatus, ReviewCheck, ReviewStatus
from sb_processor.review.checks import required_checks
from sb_processor.review.context import AgentBRequest, ProposedReviewChange, SourcePageEvidence
from sb_processor.review.runner import OpenAIAgentBClient


def _request() -> AgentBRequest:
    return AgentBRequest(workflow="university", proposal_change=ProposedReviewChange(
        action=Action.CREATE, note_type="concept", title="A", target_path="Dots/A.md",
        reason="test", proposed_final_content="# A\nSupported.", sources=[],
        candidate_existing_notes=[], original_content_hash=None), proposal_summary="",
        source_metadata={}, source_evidence=[SourcePageEvidence(page_number=1, text="Supported.")],
        source_pages_available=1, evidence_selection="explicit", affected_existing_notes=[],
        retrieval_evidence=[], review_instructions="rules", required_checks=required_checks("concept"))


def test_openai_reviewer_forwards_config_and_records_usage():
    parsed = ChangeReview(status=ReviewStatus.PASS, issues=[], checks=[
        ReviewCheck(category=category, status=CheckStatus.PASS) for category in required_checks("concept")])

    class Responses:
        def __init__(self):
            self.kwargs = None

        def parse(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(status="completed", output_parsed=parsed,
                usage=SimpleNamespace(input_tokens=123, output_tokens=45,
                    output_tokens_details=SimpleNamespace(reasoning_tokens=10)))

    responses = Responses()
    client = OpenAIAgentBClient("gpt-5.4-mini", client=SimpleNamespace(responses=responses),
                                reasoning_effort="low")
    client.review_change(_request(), [])

    assert responses.kwargs["model"] == "gpt-5.4-mini"
    assert responses.kwargs["reasoning"] == {"effort": "low"}
    assert responses.kwargs["store"] is False
    assert client.diagnostics() == {
        "model": "gpt-5.4-mini", "reasoning_effort": "low", "semantic_calls": 1,
        "retry_calls": 0, "batch_calls": 0, "input_tokens": 123, "output_tokens": 45,
        "reasoning_tokens": 10, "runtime_seconds": 0.0,
    }
