import json
from pathlib import Path

import pymupdf

from sb_processor.agent_b import review_staged_run
from sb_processor.models import (Action, ChangeReview, NoteChange, ProcessingProposal,
                                 ReviewIssue, ReviewStatus)


def _run(tmp_path: Path, *, visual: bool = False) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    (vault / "+ Inbox").mkdir(parents=True)
    (vault / "+ Inbox" / "Agent B - University Processing Review Instructions.md").write_text("REVIEW RULES")
    source = tmp_path / "source.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "A is supported")
    doc.save(source)
    doc.close()
    run = tmp_path / "staging" / "run_1"
    run.mkdir(parents=True)
    change = NoteChange(action=Action.CREATE, note_type="concept", title="A", target_path="Dots/A.md",
                        reason="fixture", content="---\ntype: concept\n---\n# A\nA is supported.",
                        sources=[source.name], candidate_existing_notes=[], original_content_hash=None)
    proposal = ProcessingProposal(workflow="university", source=str(source), source_summary="A",
                                  vault_note_count=0, note_changes=[change], review_required=[])
    (run / "proposal.json").write_text(proposal.model_dump_json())
    (run / "request_context.json").write_text(json.dumps({
        "source_metadata": {"filename": source.name}, "source_text": "[Page 1]\nTEXT:\nA is supported" +
        ("\nVISUAL CONTENT:\nA diagram" if visual else ""),
        "visual_page_statuses": [{"page_number": 1, "status": "COMPLETE"}] if visual else [],
        "relevant_existing_notes": []}))
    (run / "source_analysis.json").write_text(json.dumps({"candidate_concepts": [
        {"proposed_name": "A", "source_pages": [1]}]}))
    (run / "retrieval_evidence.json").write_text("[]")
    return run, vault


def test_pass_stages_separate_review_and_preserves_proposal(tmp_path: Path):
    run, vault = _run(tmp_path)
    original = (run / "proposal.json").read_bytes()

    class Reviewer:
        def review_change(self, request, visual_images):
            assert request.review_instructions == "REVIEW RULES"
            assert [p.page_number for p in request.source_evidence] == [1]
            return ChangeReview(status=ReviewStatus.PASS, issues=[])

    result = review_staged_run(run, vault, Reviewer())
    assert result.overall_status == ReviewStatus.PASS
    assert (run / "agent_b" / "review.json").exists()
    assert (run / "agent_b" / "report.md").exists()
    assert (run / "agent_b" / "diagnostics.json").exists()
    assert (run / "proposal.json").read_bytes() == original


def test_semantic_issue_becomes_review_required_without_mutating_original(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer:
        def review_change(self, request, visual_images):
            return ChangeReview(status=ReviewStatus.REVIEW_REQUIRED, issues=[ReviewIssue(
                change_path=request.proposal_change.target_path, issue_type="concept_boundary", severity="high",
                explanation="May need a split", proposed_correction="Human should decide")])

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.REVIEW_REQUIRED
    assert not (run / "agent_b" / "corrected_notes").exists()


def test_visual_page_image_is_exposed_to_review_client(tmp_path: Path):
    run, vault = _run(tmp_path, visual=True)

    class Reviewer:
        def review_change(self, request, visual_images):
            assert request.source_evidence[0].visual_extraction == "A diagram"
            assert len(visual_images) == 1
            assert visual_images[0][0] == 1
            assert visual_images[0][1].startswith("data:image/png;base64,")
            return ChangeReview(status=ReviewStatus.PASS, issues=[])

    review_staged_run(run, vault, Reviewer())
    diagnostics = json.loads((run / "agent_b" / "diagnostics.json").read_text())
    assert diagnostics["visual_pages_inspected"] == [1]
