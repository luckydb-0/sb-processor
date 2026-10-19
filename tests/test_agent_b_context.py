import json
from pathlib import Path

from sb_processor.agent_b_context import build_review_request, load_review_artifacts
from sb_processor.models import Action, NoteChange, ProcessingProposal


def test_review_request_selects_provenance_pages_and_affected_notes(tmp_path: Path):
    change = NoteChange(action=Action.CREATE, note_type="concept", title="A",
                        target_path="Dots/A.md", reason="test", content="# A\nFact", sources=["s.pdf"],
                        candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="s.pdf", source_summary="test",
                                  vault_note_count=1, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({
        "source_metadata": {"filename": "s.pdf"},
        "source_text": "[Page 1]\nTEXT:\nUnrelated\n\n[Page 2]\nTEXT:\nA is defined here.\nVISUAL CONTENT:\nA diagram",
        "document_completeness": None,
        "visual_page_statuses": [{"page_number": 2, "status": "COMPLETE"}],
        "relevant_existing_notes": [{"path": "Dots/B.md", "title": "B", "note_type": "concept", "body": "Existing"}],
    }))
    (tmp_path / "source_analysis.json").write_text(json.dumps({"candidate_concepts": [
        {"proposed_name": "A", "source_pages": [2]}]}))
    (tmp_path / "retrieval_evidence.json").write_text(json.dumps([{
        "candidate_name": "A", "retrieved": [{"path": "Dots/B.md"}], "loaded_body_paths": ["Dots/B.md"]}]))
    artifacts = load_review_artifacts(tmp_path)
    request = build_review_request(artifacts, change, "RULES")
    assert [page.page_number for page in request.source_evidence] == [2]
    assert request.source_evidence[0].visual_extraction == "A diagram"
    assert [note.path for note in request.affected_existing_notes] == ["Dots/B.md"]
    assert request.review_instructions == "RULES"


def test_renamed_concept_uses_overlapping_discovery_provenance(tmp_path: Path):
    change = NoteChange(action=Action.CREATE, note_type="concept", title="Knowledge Discovery Process",
                        target_path="Dots/Knowledge Discovery Process.md", reason="normalized title",
                        content="---\ntype: concept\n---\n# Knowledge Discovery Process", sources=[],
                        candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="s.pdf", source_summary="test",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 1]\nTEXT:\nUnrelated\n\n[Page 14]\nTEXT:\nDiscovery pipeline",
        "relevant_existing_notes": []}))
    (tmp_path / "source_analysis.json").write_text(json.dumps({"candidate_concepts": [
        {"proposed_name": "Discovery Process", "source_pages": [14]}]}))
    (tmp_path / "retrieval_evidence.json").write_text("[]")
    request = build_review_request(load_review_artifacts(tmp_path), change, "RULES")
    assert [page.page_number for page in request.source_evidence] == [14]


def test_concept_does_not_borrow_map_provenance(tmp_path: Path):
    change = NoteChange(action=Action.CREATE, note_type="concept", title="Machine Learning",
                        target_path="Dots/Machine Learning.md", reason="fixture", content="# Machine Learning",
                        sources=[], candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="s.pdf", source_summary="test",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 1]\nTEXT:\nMachine Learning\n\n[Page 8]\nTEXT:\nMap only",
        "relevant_existing_notes": []}))
    (tmp_path / "source_analysis.json").write_text(json.dumps({
        "candidate_concepts": [{"proposed_name": "Machine Learning", "source_pages": [1]}],
        "candidate_maps": [{"proposed_name": "Machine Learning - Map", "source_pages": [8]}]}))
    (tmp_path / "retrieval_evidence.json").write_text("[]")
    request = build_review_request(load_review_artifacts(tmp_path), change, "RULES")
    assert [page.page_number for page in request.source_evidence] == [1]
