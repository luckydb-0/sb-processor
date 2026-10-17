import json
import pytest

from sb_processor.models import Action, DraftChange, LLMProposal
from sb_processor.pipeline import IncompleteDocumentError, process_source
from sb_processor.registry import Registry
from sb_processor.vault import scan_vault


class FakeWorkflow:
    name = "fixture"

    def prepare(self, source, vault):
        return {"source_text": "PCA reduces dimensions", "instructions": "Fixture rules"}


class FakeLLM:
    def generate_processing_proposal(self, *, context):
        return LLMProposal(
            source_summary="A short source",
            review_required=[],
            note_changes=[
                DraftChange(action=Action.CREATE, note_type="concept", title="PCA", target_path="Dots/PCA.md", reason="Reusable", content="# PCA\nNew body", sources=["source.pdf"]),
                DraftChange(action=Action.CREATE, note_type="concept", title="New Topic", target_path="Dots/New Topic.md", reason="New concept", content="# New Topic", sources=["source.pdf"]),
            ],
        )


def test_pipeline_stages_proposal_without_changing_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    old = vault / "Dots" / "Principal Component Analysis.md"
    old.write_text("---\naliases: [PCA]\n---\n# Existing\n", encoding="utf-8")
    original = old.read_bytes()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    stage = tmp_path / "stage"
    run = process_source(
        vault_path=vault,
        source_path=source,
        staging_path=stage,
        database_path=tmp_path / "db.sqlite",
        workflow=FakeWorkflow(),
        llm=FakeLLM(),
    )
    proposal = json.loads((run / "proposal.json").read_text())
    assert [c["action"] for c in proposal["note_changes"]] == ["REVIEW_REQUIRED", "CREATE"]
    assert proposal["note_changes"][0]["candidate_existing_notes"][0]["match_kind"] == "alias"
    assert (run / "notes" / "Dots" / "New Topic.md").read_text() == "# New Topic\n"
    assert old.read_bytes() == original
    assert (run / "review.md").exists()
    assert (run / "request_context.json").exists()
    diagnostics = json.loads((run / "context_diagnostics.json").read_text())
    assert diagnostics["full_note_bodies_loaded"] == 1
    assert diagnostics["total_request_chars"] > diagnostics["source_chars"]
    assert any("supplied but no decision" in item for item in proposal["review_required"])


def test_pipeline_rejects_staging_inside_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    try:
        process_source(vault_path=vault, source_path=source, staging_path=vault / "stage", database_path=tmp_path / "db.sqlite", workflow=FakeWorkflow(), llm=FakeLLM())
    except ValueError as exc:
        assert "outside the vault" in str(exc)
    else:
        raise AssertionError("Expected path safety error")


class UnsafeLLM:
    def generate_processing_proposal(self, *, context):
        return LLMProposal(source_summary="unsafe", review_required=[], note_changes=[
            DraftChange(action=Action.CREATE, note_type="concept", title="Escape", target_path="../escape.md", reason="test", content="# Escape", sources=[]),
        ])


def test_pipeline_rejects_model_path_traversal_without_writing(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage", database_path=tmp_path / "db.sqlite", workflow=FakeWorkflow(), llm=UnsafeLLM())
    proposal = json.loads((run / "proposal.json").read_text())
    assert proposal["note_changes"][0]["action"] == "REVIEW_REQUIRED"
    assert not (tmp_path / "escape.md").exists()
    assert list((run / "notes").rglob("*.md")) == []


class BlindUpdateLLM:
    def generate_processing_proposal(self, *, context):
        return LLMProposal(source_summary="update", review_required=[], note_changes=[
            DraftChange(action=Action.UPDATE, note_type="concept", title="Unrelated", target_path="Dots/Existing.md", reason="test", content="# Replacement", sources=[]),
        ])


def test_update_without_existing_body_in_model_context_requires_review(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    original = vault / "Dots" / "Existing.md"
    original.write_text("# Existing\nZebras only", encoding="utf-8")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage", database_path=tmp_path / "db.sqlite", workflow=FakeWorkflow(), llm=BlindUpdateLLM())
    proposal = json.loads((run / "proposal.json").read_text())
    assert proposal["note_changes"][0]["action"] == "REVIEW_REQUIRED"
    assert proposal["note_changes"][0]["original_content_hash"]
    assert original.read_text() == "# Existing\nZebras only"


class PartialWorkflow:
    name = "fixture"

    def prepare(self, source, vault):
        return {"source_text": "[Page 13]\nTEXT:\nDiagram\nVISUAL CONTENT: UNRESOLVED",
                "document_completeness": {"status": "PARTIAL", "text_extraction_complete": True,
                                          "visual_pages": [13], "visual_pages_processed": [],
                                          "unprocessed_visual_pages": [13]}}


class TrackingLLM(FakeLLM):
    def __init__(self):
        self.calls = []

    def generate_processing_proposal(self, *, context):
        self.calls.append(context)
        return super().generate_processing_proposal(context=context)


def test_partial_source_blocks_llm_without_override(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    llm = TrackingLLM()
    with pytest.raises(IncompleteDocumentError) as error:
        process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                       database_path=tmp_path / "db.sqlite", workflow=PartialWorkflow(), llm=llm)
    assert error.value.completeness.unprocessed_visual_pages == [13]
    assert llm.calls == []


def test_explicit_override_preserves_partial_status_in_staging(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    llm = TrackingLLM()
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                         database_path=tmp_path / "db.sqlite", workflow=PartialWorkflow(), llm=llm,
                         allow_incomplete_visuals=True)
    assert len(llm.calls) == 1
    context = json.loads((run / "request_context.json").read_text())
    proposal = json.loads((run / "proposal.json").read_text())
    assert context["incomplete_visuals_override"] is True
    assert context["document_completeness"]["unprocessed_visual_pages"] == [13]
    assert proposal["source_completeness"]["status"] == "PARTIAL"
    assert "Source is PARTIAL; unresolved visual pages: [13]" in proposal["review_required"]
    assert all(change["action"] == "REVIEW_REQUIRED" for change in proposal["note_changes"])


def test_visual_override_does_not_allow_failed_text_extraction(tmp_path):
    class FailedTextWorkflow(PartialWorkflow):
        def prepare(self, source, vault):
            context = super().prepare(source, vault)
            context["document_completeness"]["text_extraction_complete"] = False
            return context

    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    llm = TrackingLLM()
    with pytest.raises(IncompleteDocumentError):
        process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                       database_path=tmp_path / "db.sqlite", workflow=FailedTextWorkflow(), llm=llm,
                       allow_incomplete_visuals=True)
    assert llm.calls == []


def test_pipeline_excludes_unrelated_files_and_long_rules(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "Machine Learning.md").write_text("# Machine Learning\nRelevant body")
    (vault / "Dots" / "README - Machine Learning.md").write_text("# Machine Learning\nUnrelated README body")
    (vault / "+ Inbox").mkdir()
    (vault / "+ Inbox" / "Agent A - Machine Learning.md").write_text("# Machine Learning\nUnrelated prompt body")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")

    class Workflow:
        name = "fixture"

        def prepare(self, source, vault):
            return {"source_text": "[Page 1]\nTEXT:\nMachine Learning", "candidate_terms": ["Machine Learning"],
                    "instructions": "Compact", "rules": "Long historical rules", "templates": "Template",
                    "suggested_note_roots": {"concept": "Dots"}}

    llm = TrackingLLM()
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                         database_path=tmp_path / "db.sqlite", workflow=Workflow(), llm=llm)
    request = json.loads((run / "request_context.json").read_text())
    diagnostics = json.loads((run / "context_diagnostics.json").read_text())
    assert "Long historical rules" not in str(request)
    assert "README" not in str(request)
    assert "Unrelated prompt body" not in str(request)
    assert [n["path"] for n in request["relevant_existing_notes"]] == ["Dots/Machine Learning.md"]
    assert any(x["path"].endswith("README - Machine Learning.md") for x in diagnostics["excluded"])
    assert any(x["path"].startswith("+ Inbox/") for x in diagnostics["excluded"])


def test_invalid_structured_response_does_not_stage(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")

    class InvalidLLM:
        def generate_processing_proposal(self, *, context):
            return {"source_summary": "incomplete", "note_changes": [{"action": "DELETE"}], "review_required": []}

    with pytest.raises(Exception):
        process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                       database_path=tmp_path / "db.sqlite", workflow=FakeWorkflow(), llm=InvalidLLM())
    assert not (tmp_path / "stage").exists()
