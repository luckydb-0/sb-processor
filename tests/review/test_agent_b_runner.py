import json
from pathlib import Path

import pymupdf

from sb_processor.review.runner import review_staged_run
from sb_processor.models import ReviewCheck, CheckStatus, GlobalBatchReview
from sb_processor.review.checks import required_checks

def _checks(dot_status=CheckStatus.PASS):
    return [ReviewCheck(category=category, status=dot_status if category.value == "dot_promotion" else CheckStatus.PASS,
                        explanation="Independent identity unclear" if category.value == "dot_promotion" and dot_status != CheckStatus.PASS else None)
            for category in required_checks("concept")]

class _ReviewBatchMixin:
    def review_batch(self, request):
        assert request.changes
        return GlobalBatchReview(issues=[], summary="No cross-note findings")

from sb_processor.models import (Action, AliasAssessment, ChangeReview, NoteChange, ProcessingProposal,
                                 PromotionAssessment,
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
                                  vault_note_count=1, note_changes=[change], review_required=[])
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

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            assert "Detecting a problem does NOT grant permission" in request.review_instructions
            assert "proposed_final_content" in request.review_instructions
            assert "primary review target" in request.review_instructions
            assert [p.page_number for p in request.source_evidence] == [1]
            return ChangeReview(checks=_checks(), status=ReviewStatus.PASS, issues=[], promotion_assessment=PromotionAssessment(
                status=ReviewStatus.PASS, explanation="Independent concept", proposed_correction=""))

    result = review_staged_run(run, vault, Reviewer())
    assert result.overall_status == ReviewStatus.PASS
    assert (run / "agent_b" / "review.json").exists()
    assert (run / "agent_b" / "detailed_report.md").exists()
    assert (run / "SUMMARY.md").exists()
    assert "## Needs human decision" in (run / "SUMMARY.md").read_text()
    assert (run / "agent_b" / "diagnostics.json").exists()
    assert (run / "proposal.json").read_bytes() == original


def test_semantic_issue_becomes_review_required_without_mutating_original(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            return ChangeReview(checks=_checks(), status=ReviewStatus.REVIEW_REQUIRED, issues=[ReviewIssue(
                change_path=request.proposal_change.target_path, issue_type="concept_boundary", severity="high",
                explanation="May need a split", proposed_correction="Human should decide", source_pages=[1])],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                                                         explanation="Independent concept", proposed_correction=""))

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.REVIEW_REQUIRED
    assert not (run / "agent_b" / "corrected_notes").exists()


def test_visual_page_image_is_exposed_to_review_client(tmp_path: Path):
    run, vault = _run(tmp_path, visual=True)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            assert request.source_evidence[0].visual_extraction == "A diagram"
            assert len(visual_images) == 1
            assert visual_images[0][0] == 1
            assert visual_images[0][1].startswith("data:image/png;base64,")
            return ChangeReview(checks=_checks(), status=ReviewStatus.PASS, issues=[], promotion_assessment=PromotionAssessment(
                status=ReviewStatus.PASS, explanation="Independent concept", proposed_correction=""))

    review_staged_run(run, vault, Reviewer())
    diagnostics = json.loads((run / "agent_b" / "diagnostics.json").read_text())
    assert diagnostics["visual_pages_inspected"] == [1]


def test_review_rejects_mismatched_vault_before_model_call(tmp_path: Path):
    run, vault = _run(tmp_path)
    (vault / "extra.md").write_text("# Extra")

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            raise AssertionError("Model must not be called")

    import pytest
    with pytest.raises(ValueError, match="vault snapshot"):
        review_staged_run(run, vault, Reviewer())


def test_invalid_alias_and_weak_dot_are_reported_separately(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    proposal.note_changes[0].content = "---\ntype: concept\naliases: [K-Fold A]\n---\n# A"
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            assert request.aliases_to_review == ["K-Fold A"]
            return ChangeReview(checks=_checks(CheckStatus.FAIL), status=ReviewStatus.PASS, issues=[ReviewIssue(
                change_path="Dots/A.md", issue_type="dot_promotion", severity="medium",
                explanation="Independent identity unclear", proposed_correction="Human decides", source_pages=[1])], alias_assessments=[AliasAssessment(
                alias="K-Fold A", status=ReviewStatus.REVIEW_REQUIRED, relation="SUBTYPE",
                explanation="Subtype", proposed_correction="Remove alias")],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.REVIEW_REQUIRED,
                    explanation="Independent identity unclear", proposed_correction="Human decides"))

    result = review_staged_run(run, vault, Reviewer())
    assert result.overall_status == ReviewStatus.REVIEW_REQUIRED
    assert {issue.issue_type for issue in result.issues} == {"alias", "dot_promotion"}
    assert result.reviewed_changes[0].status == ReviewStatus.REVIEW_REQUIRED  # Dot identity still needs judgment.


def test_generic_runner_accepts_a_workflow_review_adapter(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    proposal.workflow = "book"
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class BookReviewAdapter:
        def instructions(self, vault):
            return "BOOK RULES"

        def build_request(self, artifacts, change, instructions):
            from sb_processor.review.context import build_review_request
            return build_review_request(artifacts, change, instructions)

        def visual_images(self, source, request):
            return []

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            assert request.workflow == "book" and request.review_instructions == "BOOK RULES"
            return ChangeReview(checks=_checks(), status=ReviewStatus.PASS, issues=[], promotion_assessment=PromotionAssessment(
                status=ReviewStatus.PASS, explanation="Independent", proposed_correction=""))

    result = review_staged_run(run, vault, Reviewer(), adapter=BookReviewAdapter())
    assert result.overall_status == ReviewStatus.PASS


def test_uncited_subtype_claim_requires_review(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    proposal.note_changes[0].content = "---\ntype: concept\naliases: [K-Fold A]\n---\n# A"
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            return ChangeReview(checks=_checks(), status=ReviewStatus.REVIEW_REQUIRED, issues=[], alias_assessments=[AliasAssessment(
                alias="K-Fold A", relation="SUBTYPE", status=ReviewStatus.REVIEW_REQUIRED,
                explanation="A subtype of A", proposed_correction="Review")],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                    explanation="Independent", proposed_correction=""))

    result = review_staged_run(run, vault, Reviewer())
    assert result.overall_status == ReviewStatus.REVIEW_REQUIRED
    assert "lacks cited evidence" in result.issues[0].explanation


def test_review_does_not_overwrite_existing_agent_b_artifacts(tmp_path: Path):
    run, vault = _run(tmp_path)
    (run / "agent_b").mkdir()
    (run / "agent_b" / "review.json").write_text("old result")

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            raise AssertionError("Model must not be called")

    import pytest
    with pytest.raises(FileExistsError, match="already exists"):
        review_staged_run(run, vault, Reviewer())
    assert (run / "agent_b" / "review.json").read_text() == "old result"


def test_per_note_review_discards_issue_for_another_change(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            return ChangeReview(checks=_checks(), status=ReviewStatus.REVIEW_REQUIRED,
                issues=[ReviewIssue(change_path="Dots/Other.md", issue_type="concept_boundary", severity="medium",
                                    explanation="Other may need split", proposed_correction="Review", source_pages=[1])],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                    explanation="Independent", proposed_correction="", foundational_identity=True))

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.PASS
    assert result.issues == []


def test_orthographic_alias_does_not_require_invented_distinction(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    change = proposal.note_changes[0]
    change.title = "Dataset"
    change.target_path = "Dots/Dataset.md"
    change.content = "---\ntype: concept\naliases: [Data Set]\n---\n# Dataset\nA is supported."
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            return ChangeReview(checks=_checks(), status=ReviewStatus.PASS, issues=[],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                    explanation="Independent", proposed_correction="", foundational_identity=True))

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.PASS
    assert not any(issue.issue_type.value == "alias" for issue in result.issues)
    assert next(check for check in result.reviewed_changes[0].checks if check.category.value == "aliases").status == CheckStatus.PASS


def test_failed_check_still_unsupported_after_retry_becomes_insufficient(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "source_fidelity").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.PASS, issues=[],
                promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                    explanation="Independent", proposed_correction=""))

        def review_failed_checks(self, request, visual_images):
            return {"checks": [{"category": "source_fidelity", "status": "FAIL"}],
                    "issues": [], "status": "REVIEW_REQUIRED"}

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.PASS
    assert not result.issues
    assert any(check.category.value == "source_fidelity" and check.status == CheckStatus.INSUFFICIENT_EVIDENCE
               for check in result.reviewed_changes[0].checks)


def test_distinct_semantic_provenance_issue_survives_pdf_metadata_fix(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    proposal.note_changes[0].content = "---\ntype: concept\nsource_file: source.pdf\n---\n# A\nA is supported."
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            return ChangeReview(checks=_checks(), status=ReviewStatus.FIX, issues=[ReviewIssue(
                change_path=request.proposal_change.target_path, issue_type="provenance", severity="medium",
                explanation="Wrong Lecture wikilink in provenance", proposed_correction="Correct the Lecture link",
                source_pages=[1])], promotion_assessment=PromotionAssessment(status=ReviewStatus.PASS,
                    explanation="Independent", proposed_correction=""))

    result = review_staged_run(run, vault, Reviewer())
    assert any("Wrong Lecture wikilink" in issue.explanation for issue in result.issues)


def test_unsupported_fail_retries_only_failed_category_and_can_pass(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "source_fidelity").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.REVIEW_REQUIRED, issues=[])

        def review_failed_checks(self, request, visual_images):
            assert [category.value for category in request.categories] == ["source_fidelity"]
            assert request.previous_checks[0].status == CheckStatus.FAIL
            assert "A is supported" in request.review_context.proposal_change.proposed_final_content
            return {"checks": [{"category": "source_fidelity", "status": "PASS"}],
                    "issues": [], "status": "PASS"}

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.PASS
    assert not result.issues
    diagnostics = json.loads((run / "agent_b" / "diagnostics.json").read_text())
    assert diagnostics["retry_count"] == 1
    assert diagnostics["retry_checks_changed_to_pass"] == 1
    assert (run / "agent_b" / "retries" / "001_response.json").is_file()


def test_targeted_retry_recovers_supported_source_issue(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "source_fidelity").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.REVIEW_REQUIRED, issues=[])

        def review_failed_checks(self, request, visual_images):
            return {"checks": [{"category": "source_fidelity", "status": "FAIL",
                                "explanation": "The proposed claim exceeds page 1"}],
                    "issues": [{"change_path": "Dots/A.md", "issue_type": "source_fidelity",
                                "severity": "medium", "explanation": "Proposed claim exceeds the source",
                                "proposed_correction": "Remove the unsupported wording", "source_pages": [1]}],
                    "status": "FIX"}

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.FIX
    assert any(issue.issue_type.value == "source_fidelity" for issue in result.issues)
    diagnostics = json.loads((run / "agent_b" / "diagnostics.json").read_text())
    assert diagnostics["retry_issues_recovered"] == 1


def test_retry_insufficient_source_evidence_does_not_force_human_decision(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "source_fidelity").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.REVIEW_REQUIRED, issues=[])

        def review_failed_checks(self, request, visual_images):
            return {"checks": [{"category": "source_fidelity", "status": "INSUFFICIENT_EVIDENCE",
                                "explanation": "Page 1 is too sparse to establish the concern"}],
                    "issues": [], "status": "PASS"}

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.PASS
    assert not result.issues
    assert any(check.category.value == "source_fidelity" and check.status == CheckStatus.INSUFFICIENT_EVIDENCE
               for check in result.reviewed_changes[0].checks)
    assert "Review evidence gaps" not in (run / "SUMMARY.md").read_text()


def test_retry_insufficient_boundary_evidence_preserves_real_decision(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "concept_boundaries").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.REVIEW_REQUIRED, issues=[])

        def review_failed_checks(self, request, visual_images):
            return {"checks": [{"category": "concept_boundaries", "status": "INSUFFICIENT_EVIDENCE",
                                "explanation": "The supplied notes do not resolve whether the concepts overlap"}],
                    "issues": [], "status": "REVIEW_REQUIRED"}

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.REVIEW_REQUIRED
    assert any(issue.issue_type.value == "concept_boundary" for issue in result.issues)


def test_supported_first_pass_fail_does_not_retry(tmp_path: Path):
    run, vault = _run(tmp_path)

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "source_fidelity").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.FIX, issues=[ReviewIssue(
                change_path="Dots/A.md", issue_type="source_fidelity", severity="medium",
                explanation="Source does not support this claim", proposed_correction="Remove it", source_pages=[1])])

        def review_failed_checks(self, request, visual_images):
            raise AssertionError("Supported first-pass finding must not be retried")

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.FIX
    assert json.loads((run / "agent_b" / "diagnostics.json").read_text())["retry_count"] == 0


def test_deterministic_provenance_fail_does_not_retry_semantics(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    proposal.note_changes[0].content = "---\ntype: concept\nsource_file: source.pdf\n---\n# A\nA is supported."
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            assert any(item["issue_type"] == "provenance" for item in request.deterministic_findings)
            checks = _checks()
            next(check for check in checks if check.category.value == "provenance").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.FIX, issues=[])

        def review_failed_checks(self, request, visual_images):
            raise AssertionError("Objective provenance is already validated")

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.FIX
    assert json.loads((run / "agent_b" / "diagnostics.json").read_text())["retry_count"] == 0


def test_nonblocking_insufficient_retry_keeps_objective_fix_auto_fixable(tmp_path: Path):
    run, vault = _run(tmp_path)
    proposal = ProcessingProposal.model_validate_json((run / "proposal.json").read_text())
    proposal.note_changes[0].content = "---\ntype: concept\nsource_file: source.pdf\n---\n# A\nA is supported."
    (run / "proposal.json").write_text(proposal.model_dump_json())

    class Reviewer(_ReviewBatchMixin):
        def review_change(self, request, visual_images):
            checks = _checks()
            next(check for check in checks if check.category.value == "source_fidelity").status = CheckStatus.FAIL
            return ChangeReview(checks=checks, status=ReviewStatus.REVIEW_REQUIRED, issues=[])

        def review_failed_checks(self, request, visual_images):
            return {"checks": [{"category": "source_fidelity", "status": "INSUFFICIENT_EVIDENCE"}],
                    "issues": [], "status": "PASS"}

    result = review_staged_run(run, vault, Reviewer())
    assert result.reviewed_changes[0].status == ReviewStatus.FIX
    assert {issue.issue_type.value for issue in result.issues} == {"provenance"}
