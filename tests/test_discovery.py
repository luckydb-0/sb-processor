from pathlib import Path

import pytest
from pydantic import ValidationError

from sb_processor.agent_a import build_discovery_request
from sb_processor.llm import OpenAILLMClient
from sb_processor.models import SourceAnalysis


def test_discovery_request_has_source_but_no_existing_concept_bodies():
    request, diagnostics = build_discovery_request("university", Path("lecture.pdf"), {
        "source_text": "[Page 1]\nTEXT:\nData Mining",
        "instructions": "Compact instructions",
        "rules": "Long historical protocol",
        "templates": "Large note templates",
        "document_completeness": {"status": "PARTIAL", "text_extraction_complete": True,
                                  "visual_pages": [2], "visual_pages_processed": [],
                                  "unprocessed_visual_pages": [2]},
        "incomplete_visuals_override": True,
    })
    payload = request.model_dump(mode="json")
    assert payload["source_text"].startswith("[Page 1]")
    assert payload["document_completeness"]["status"] == "PARTIAL"
    assert payload["incomplete_visuals_override"] is True
    assert "existing_notes" not in str(payload)
    assert "Long historical protocol" not in str(payload)
    assert "Large note templates" not in str(payload)
    assert diagnostics.existing_note_chars == 0


def test_source_analysis_rejects_vault_actions():
    with pytest.raises(ValidationError):
        SourceAnalysis.model_validate({"source_identity": "lecture", "candidate_concepts": [
            {"proposed_name": "Data Mining", "source_pages": [1], "reason": "Core concept", "action": "CREATE"}
        ], "candidate_maps": [], "source_level_observations": []})


def test_openai_discovery_uses_structured_output():
    class Responses:
        def parse(self, **kwargs):
            self.kwargs = kwargs
            return type("Response", (), {"status": "completed", "output_parsed": SourceAnalysis(
                source_identity="lecture", candidate_concepts=[], candidate_maps=[], source_level_observations=[])})()
    responses = Responses()
    sdk = type("SDK", (), {"responses": responses})()
    result = OpenAILLMClient("test-model", client=sdk).analyze_source(context={"source_text": "[Page 1]"})
    assert result.source_identity == "lecture"
    assert responses.kwargs["text_format"] is SourceAnalysis
    assert responses.kwargs["store"] is False
