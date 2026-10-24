from pathlib import Path

from sb_processor.agent_a import build_agent_a_request
from sb_processor.knowledge.registry import Registry
from sb_processor.knowledge.retrieval import RetrievalPolicy, retrieve_notes
from sb_processor.knowledge.vault import scan_vault


def test_structured_request_uses_compact_instructions_and_measures_context(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "Machine Learning.md").write_text("# Machine Learning\nExisting body", encoding="utf-8")
    (vault / "README.md").write_text("# Machine Learning\nHuge unrelated body", encoding="utf-8")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    retrieval = retrieve_notes(registry, "[Page 1]\nTEXT:\nMachine Learning", ["Machine Learning"],
                               RetrievalPolicy(roots={"concept": "Dots"}))
    request, diagnostics = build_agent_a_request("university", Path("lecture.pdf"), {
        "source_text": "[Page 1]\nTEXT:\nMachine Learning",
        "instructions": "Compact instructions",
        "rules": "Long historical rules must not enter request",
        "templates": "Lecture template",
        "document_completeness": {"status": "COMPLETE", "text_extraction_complete": True,
                                  "visual_pages": [], "visual_pages_processed": [], "unprocessed_visual_pages": []},
        "suggested_note_roots": {"concept": "Dots"},
    }, retrieval)
    payload = request.model_dump(mode="json")
    assert payload["workflow_instructions"] == "Compact instructions"
    assert "Long historical rules" not in str(payload)
    assert payload["source_text"].startswith("[Page 1]\nTEXT:")
    assert payload["document_completeness"]["status"] == "COMPLETE"
    assert [n["path"] for n in payload["relevant_existing_notes"]] == ["Dots/Machine Learning.md"]
    assert diagnostics.candidate_notes_considered == 1
    assert diagnostics.full_note_bodies_loaded == 1
    assert diagnostics.existing_note_chars == len("Existing body") + len("# Machine Learning\n")
    assert diagnostics.total_request_chars > diagnostics.source_chars
    assert any(x.path == "README.md" for x in diagnostics.excluded)
