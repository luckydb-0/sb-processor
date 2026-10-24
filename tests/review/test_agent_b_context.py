import json
from pathlib import Path

from sb_processor.review.context import build_review_request, load_review_artifacts
from sb_processor.models import Action, NoteChange, ProcessingProposal
from sb_processor.models import ReviewIssue, SourceReference
from sb_processor.review.retry import valid_issue_evidence


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


def test_dataset_update_serializes_proposed_final_content_separately_from_old_note(tmp_path: Path):
    """The v1.1 Dataset reviewer treated the pre-update body as the proposed result."""
    old = "A dataset is a table of examples."
    proposed = ("---\ntype: concept\n---\n# Dataset\n"
                "Real-world data need not start as tables; some techniques require transformation into a table-like form.")
    change = NoteChange(action=Action.UPDATE, note_type="concept", title="Dataset",
        target_path="Dots/Dataset.md", reason="Add broader account", content=proposed,
        sources=["lecture.pdf"], candidate_existing_notes=[], original_content_hash="prior-hash")
    proposal = ProcessingProposal(workflow="university", source="lecture.pdf", source_summary="Dataset",
        vault_note_count=1, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 1]\nTEXT:\nReal data may require transformation into tables.",
        "relevant_existing_notes": [{"path": "Dots/Dataset.md", "title": "Dataset",
                                    "note_type": "concept", "body": old}]}))
    (tmp_path / "source_analysis.json").write_text(json.dumps({"candidate_concepts": [
        {"proposed_name": "Dataset", "source_pages": [1]}]}))
    (tmp_path / "retrieval_evidence.json").write_text("[]")

    payload = build_review_request(load_review_artifacts(tmp_path), change, "RULES").model_dump(mode="json")
    assert "transformation into a table-like form" in payload["proposal_change"]["proposed_final_content"]
    assert "content" not in payload["proposal_change"]
    assert payload["affected_existing_notes"][0]["existing_content"] == old
    assert "body" not in payload["affected_existing_notes"][0]

    request = build_review_request(load_review_artifacts(tmp_path), change, "RULES")
    vague_loss = ReviewIssue(change_path="Dots/Dataset.md", issue_type="existing_note",
        severity="medium", explanation="The old note lacks details added by the update",
        proposed_correction="Restore the old note", evidence_refs=[SourceReference(
            note_path="Dots/Dataset.md", reference="Existing dataset definition")])
    assert not valid_issue_evidence(vague_loss, request)
    supported_loss = vague_loss.model_copy(update={"evidence_refs": [SourceReference(
        note_path="Dots/Dataset.md", reference='Old note says "A dataset is a table of examples."')],
        "explanation": "This old statement is missing from the proposed final note"})
    assert valid_issue_evidence(supported_loss, request)


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


def test_request_lists_each_proposed_alias_for_explicit_review(tmp_path: Path):
    change = NoteChange(action=Action.CREATE, note_type="concept", title="Cross-Validation",
                        target_path="Dots/Cross-Validation.md", reason="fixture",
                        content="---\ntype: concept\naliases:\n  - K-Fold Cross-Validation\n---\n# Cross-Validation",
                        sources=[], candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="s.pdf", source_summary="test",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 1]\nTEXT:\nCross validation", "relevant_existing_notes": []}))
    (tmp_path / "source_analysis.json").write_text("{}")
    (tmp_path / "retrieval_evidence.json").write_text("[]")
    request = build_review_request(load_review_artifacts(tmp_path), change, "RULES")
    assert request.aliases_to_review == ["K-Fold Cross-Validation"]
    assert request.requires_promotion_assessment


def test_explicit_note_page_reference_is_prioritized(tmp_path: Path):
    change = NoteChange(action=Action.CREATE, note_type="concept", title="A", target_path="Dots/A.md",
                        reason="fixture", content="---\ntype: concept\n---\n# A\n**Pages/slides:** 3-4",
                        sources=[], candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="s.pdf", source_summary="test",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 1]\nTEXT:\nA\n[Page 3]\nTEXT:\nClaim\n[Page 4]\nTEXT:\nDiagram",
        "relevant_existing_notes": []}))
    (tmp_path / "source_analysis.json").write_text(json.dumps({"candidate_concepts": [
        {"proposed_name": "A", "source_pages": [1]}]}))
    (tmp_path / "retrieval_evidence.json").write_text("[]")
    request = build_review_request(load_review_artifacts(tmp_path), change, "RULES", max_pages=2)
    assert [page.page_number for page in request.source_evidence] == [3, 4]


def test_lecture_parenthetical_page_citations_select_pages(tmp_path: Path):
    change = NoteChange(action=Action.CREATE, note_type="lecture", title="Lecture 1",
                        target_path="Sources/Lecture 1.md", reason="fixture",
                        content="---\ntype: lecture\n---\n# Lecture 1\nThe source explains A (pp. 3-4).",
                        sources=[], candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source="s.pdf", source_summary="test",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    (tmp_path / "proposal.json").write_text(proposal.model_dump_json())
    (tmp_path / "request_context.json").write_text(json.dumps({"source_metadata": {},
        "source_text": "[Page 1]\nTEXT:\nTitle\n[Page 3]\nTEXT:\nA\n[Page 4]\nTEXT:\nB",
        "relevant_existing_notes": []}))
    (tmp_path / "source_analysis.json").write_text("{}")
    (tmp_path / "retrieval_evidence.json").write_text("[]")
    request = build_review_request(load_review_artifacts(tmp_path), change, "RULES")
    assert [page.page_number for page in request.source_evidence] == [3, 4]
