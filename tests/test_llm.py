from sb_processor.llm import OpenAILLMClient
from sb_processor.models import LLMProposal


class Responses:
    def __init__(self):
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return type("Response", (), {"status": "completed", "output_parsed": LLMProposal(source_summary="Test", note_changes=[], review_required=[])})()


def test_openai_client_uses_responses_structured_parse():
    responses = Responses()
    sdk = type("SDK", (), {"responses": responses})()
    result = OpenAILLMClient("test-model", client=sdk).generate_processing_proposal(context={"source_text": "hello"})
    assert result.source_summary == "Test"
    assert responses.kwargs["text_format"] is LLMProposal
    assert responses.kwargs["store"] is False
    assert responses.kwargs["model"] == "test-model"
