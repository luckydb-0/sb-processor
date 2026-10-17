import json

from sb_processor.models import Action, DraftChange, LLMProposal
from sb_processor.pipeline import process_source
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
