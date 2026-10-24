from pathlib import Path

import pytest
from pydantic import ValidationError

from sb_processor.processing.agent_a import build_discovery_request, enrich_definition_candidates, select_analysis_candidates
from sb_processor.processing.llm import OpenAILLMClient
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


def test_discovery_can_name_source_level_notes_without_vault_action():
    analysis = SourceAnalysis.model_validate({"source_identity": "Machine Learning lecture 01",
        "candidate_concepts": [], "candidate_maps": [], "source_level_observations": [],
        "source_note_candidates": [{"note_type": "lecture", "proposed_name": "Machine Learning - 01 - Introduction",
                                    "source_pages": [1], "reason": "Lecture title appears on first page"}]})
    assert analysis.source_note_candidates[0].note_type == "lecture"


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


def test_discovery_cap_keeps_high_importance_and_reports_omissions():
    analysis = SourceAnalysis.model_validate({"source_identity": "fixture", "candidate_maps": [],
        "source_level_observations": [], "candidate_concepts": [
            {"proposed_name": "Small example", "reason": "Example", "importance": "LOW"},
            {"proposed_name": "Data Mining", "reason": "Core", "importance": "HIGH"},
            {"proposed_name": "Classification", "reason": "Task family", "importance": "HIGH"},
            {"proposed_name": "Minor detail", "reason": "Detail", "importance": "LOW"}]})
    selected, omitted = select_analysis_candidates(analysis, max_concepts=2)
    assert [c.proposed_name for c in selected.candidate_concepts] == ["Data Mining", "Classification"]
    assert [c.proposed_name for c in omitted] == ["Small example", "Minor detail"]


def test_explicit_definition_heading_survives_discovery_cap():
    analysis = SourceAnalysis(source_identity="fixture", candidate_concepts=[
        {"proposed_name": "Other Topic", "reason": "Mentioned", "importance": "MEDIUM"}],
        candidate_maps=[], source_level_observations=[])
    enriched = enrich_definition_candidates(analysis, "[Page 50]\nTEXT:\nWhat is a data set?\nA set of examples")
    selected, omitted = select_analysis_candidates(enriched, max_concepts=1)
    assert selected.candidate_concepts[0].proposed_name == "Data Set"
    assert selected.candidate_concepts[0].source_pages == [50]
    assert [c.proposed_name for c in omitted] == ["Other Topic"]


def test_open_ended_question_is_not_promoted_to_concept():
    analysis = SourceAnalysis(source_identity="fixture", candidate_concepts=[],
                              candidate_maps=[], source_level_observations=[])
    enriched = enrich_definition_candidates(analysis, "[Page 34]\nTEXT:\nWhat is typical cell phone usage of this customer segment?")
    assert enriched.candidate_concepts == []
    enriched = enrich_definition_candidates(analysis, "[Page 34]\nTEXT:\nWhat is the typical cell phone usage of this customer segment?")
    assert enriched.candidate_concepts == []
