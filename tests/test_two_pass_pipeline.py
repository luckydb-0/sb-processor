import json

from sb_processor.models import Action, CandidateConcept, ConceptRelation, ConceptResolution, DraftChange, LLMProposal, SourceAnalysis
from sb_processor.processing.pipeline import process_source
from sb_processor.knowledge.semantic import SemanticHit


class Workflow:
    name = "fixture"

    def prepare(self, source, vault):
        return {"source_text": "[Page 1]\nTEXT:\nData Mining uses datasets.",
                "instructions": "Compact rules", "templates": "# Concept template",
                "suggested_note_roots": {"concept": "Dots", "map": "Maps"},
                "document_completeness": {"status": "COMPLETE", "text_extraction_complete": True,
                                          "visual_pages": [], "visual_pages_processed": [], "unprocessed_visual_pages": []}}


class Semantic:
    def search(self, query, *, limit):
        return [SemanticHit("Dots/Data Mining.md", .73)] if query == "Data Mining" else []


class LLM:
    def __init__(self):
        self.first = None
        self.second = None

    def analyze_source(self, *, context):
        self.first = context
        return SourceAnalysis(source_identity="lecture 1", candidate_concepts=[
            CandidateConcept(proposed_name="Data Mining", source_pages=[1], reason="Core topic")],
            candidate_maps=[], source_level_observations=[])

    def generate_processing_proposal(self, *, context):
        self.second = context
        return LLMProposal(source_summary="Data Mining", review_required=[], concept_resolutions=[
            ConceptResolution(candidate_name="Data Mining", relation=ConceptRelation.EQUIVALENT_EXISTING,
                              existing_path="Dots/Data Mining.md", reason="Same concept; source adds detail")],
            note_changes=[DraftChange(action=Action.UPDATE, note_type="concept", title="Data Mining",
                                      target_path="Dots/Data Mining.md", reason="Add source detail",
                                      content="# Data Mining\nExisting body\nNew detail", sources=["Page 1"])])


def test_data_mining_body_reaches_second_pass_after_discovery(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    note = vault / "Dots" / "Data Mining.md"
    note.write_text("# Data Mining\nExisting body", encoding="utf-8")
    for i in range(20):
        (vault / "Dots" / f"Unrelated {i}.md").write_text(f"# Unrelated {i}\nbody", encoding="utf-8")
    (vault / "README.md").write_text("# Data Mining\nUnrelated repository README", encoding="utf-8")
    source = tmp_path / "lecture.pdf"
    source.write_bytes(b"fixture")
    llm = LLM()
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                         database_path=tmp_path / "registry.sqlite", workflow=Workflow(), llm=llm,
                         semantic_index=Semantic())
    assert "relevant_existing_notes" not in llm.first
    assert llm.second["source_analysis"]["candidate_concepts"][0]["proposed_name"] == "Data Mining"
    assert llm.second["relevant_existing_notes"][0]["path"] == "Dots/Data Mining.md"
    assert "Existing body" in llm.second["relevant_existing_notes"][0]["body"]
    assert llm.second["candidate_evidence"][0]["retrieved"][0]["semantic_score"] == .73
    assert "semantic_observations" not in llm.second["candidate_evidence"][0]
    assert json.loads((run / "retrieval_evidence.json").read_text())[0]["semantic_observations"][0]["score"] == .73
    assert llm.second["candidate_existing_notes"] == []  # metadata lives only in per-candidate evidence
    assert "README" not in str(llm.second)
    assert json.loads((run / "proposal.json").read_text())["note_changes"][0]["action"] == "UPDATE"
    assert (run / "source_analysis.json").exists()
    assert (run / "pass1_diagnostics.json").exists()
    assert (run / "retrieval_evidence.json").exists()
    assert note.read_text() == "# Data Mining\nExisting body"


def test_ambiguous_resolution_cannot_stage_automatic_update(tmp_path):
    class AmbiguousLLM(LLM):
        def generate_processing_proposal(self, *, context):
            draft = super().generate_processing_proposal(context=context)
            draft.concept_resolutions[0].relation = ConceptRelation.AMBIGUOUS
            return draft

    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "Data Mining.md").write_text("# Data Mining\nExisting body")
    source = tmp_path / "lecture.pdf"
    source.write_bytes(b"fixture")
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                         database_path=tmp_path / "registry.sqlite", workflow=Workflow(), llm=AmbiguousLLM())
    proposal = json.loads((run / "proposal.json").read_text())
    assert proposal["note_changes"][0]["action"] == "REVIEW_REQUIRED"
    assert any("ambiguous" in item.lower() for item in proposal["review_required"])


def test_broad_alias_does_not_auto_merge_narrower_title(tmp_path):
    class ClassificationLLM:
        def analyze_source(self, *, context):
            return SourceAnalysis(source_identity="lecture", candidate_concepts=[
                CandidateConcept(proposed_name="Classification", source_pages=[1], reason="Task family")],
                candidate_maps=[], source_level_observations=[])

        def generate_processing_proposal(self, *, context):
            assert context["candidate_evidence"][0]["retrieved"][0]["match_kind"] == "alias"
            return LLMProposal(source_summary="Classification", review_required=[], concept_resolutions=[
                ConceptResolution(candidate_name="Classification", relation=ConceptRelation.EQUIVALENT_EXISTING,
                                  existing_path="Dots/Predictive Classification.md", reason="Alias")], note_changes=[
                DraftChange(action=Action.UPDATE, note_type="concept", title="Predictive Classification",
                            target_path="Dots/Predictive Classification.md", reason="Merge", content="# Predictive Classification\nUpdated",
                            sources=["Page 1"])])

    class ClassificationWorkflow(Workflow):
        def prepare(self, source, vault):
            context = super().prepare(source, vault)
            context["source_text"] = "[Page 1]\nTEXT:\nClassification"
            return context

    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "Predictive Classification.md").write_text(
        "---\naliases: [Classification]\n---\n# Predictive Classification\nExisting")
    source = tmp_path / "lecture.pdf"
    source.write_bytes(b"fixture")
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                         database_path=tmp_path / "registry.sqlite", workflow=ClassificationWorkflow(),
                         llm=ClassificationLLM())
    change = json.loads((run / "proposal.json").read_text())["note_changes"][0]
    assert change["action"] == "REVIEW_REQUIRED"
    assert "scope" in str(json.loads((run / "proposal.json").read_text())["review_required"]).lower()


def test_no_change_without_existing_target_requires_review(tmp_path):
    class MissingLLM(LLM):
        def generate_processing_proposal(self, *, context):
            return LLMProposal(source_summary="none", review_required=[], concept_resolutions=[
                ConceptResolution(candidate_name="Data Mining", relation=ConceptRelation.NEW_CONCEPT,
                                  reason="No note")], note_changes=[
                DraftChange(action=Action.NO_CHANGE, note_type="concept", title="Data Mining",
                            target_path="Dots/Data Mining.md", reason="No change", content="", sources=[])])

    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "lecture.pdf"
    source.write_bytes(b"fixture")
    run = process_source(vault_path=vault, source_path=source, staging_path=tmp_path / "stage",
                         database_path=tmp_path / "registry.sqlite", workflow=Workflow(), llm=MissingLLM())
    proposal = json.loads((run / "proposal.json").read_text())
    assert proposal["note_changes"][0]["action"] == "REVIEW_REQUIRED"
