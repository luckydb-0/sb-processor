import hashlib
import json
from pathlib import Path

from sb_processor.cli import build_parser, main
import pytest


def test_process_accepts_pdf_extractor_selection():
    args = build_parser().parse_args(["process", "--workflow", "university", "--source", "lecture.pdf", "--vault", "vault", "--pdf-extractor", "anydoc"])
    assert args.pdf_extractor == "anydoc"


def test_process_accepts_explicit_incomplete_override():
    args = build_parser().parse_args(["process", "--workflow", "university", "--source", "lecture.pdf",
                                      "--vault", "vault", "--allow-incomplete-visuals", "--skip-visual"])
    assert args.allow_incomplete_visuals is True
    assert args.skip_visual is True


def test_ingest_pdf_accepts_local_benchmark_options():
    args = build_parser().parse_args(["ingest-pdf", "--source", "lecture.pdf", "--vault", "vault",
                                      "--visual-model", "gpt-4o-mini"])
    assert args.visual_model == "gpt-4o-mini"
    default = build_parser().parse_args(["ingest-pdf", "--source", "lecture.pdf", "--vault", "vault"])
    assert default.visual_model == "gpt-5.4"


def test_compare_pdf_command_accepts_source():
    args = build_parser().parse_args(["compare-pdf", "--source", "lecture.pdf", "--vault", "vault"])
    assert args.command == "compare-pdf"


def test_compare_pdf_requires_vault_for_output_safety():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["compare-pdf", "--source", "lecture.pdf"])


def test_compare_pdf_refuses_output_inside_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    output = vault / "comparison"
    with pytest.raises(SystemExit):
        main(["compare-pdf", "--source", "lecture.pdf", "--vault", str(vault), "--output-dir", str(output)])
    assert not output.exists()


def test_ingest_pdf_refuses_output_or_cache_inside_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(SystemExit):
        main(["ingest-pdf", "--source", "lecture.pdf", "--vault", str(vault),
              "--output-dir", str(vault / "ingestion")])
    with pytest.raises(SystemExit):
        main(["ingest-pdf", "--source", "lecture.pdf", "--vault", str(vault),
              "--visual-cache", str(vault / "cache")])


def reconciliation_fixture(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "run_1"
    run.mkdir()
    proposal = {
        "workflow": "university",
        "source": "lecture.pdf",
        "source_summary": "Fixture",
        "vault_note_count": 0,
        "note_changes": [{
            "action": "CREATE",
            "note_type": "concept",
            "title": "Topic",
            "target_path": "Dots/Topic.md",
            "reason": "fixture",
            "content": "---\ntype: concept\n---\n# Topic\nSee [[Missing]].\n",
            "sources": ["lecture.pdf"],
            "candidate_existing_notes": [],
            "original_content_hash": None,
        }],
        "review_required": [],
        "source_completeness": None,
        "concept_resolutions": [],
    }
    proposal_text = json.dumps(proposal, indent=2) + "\n"
    (run / "proposal.json").write_text(proposal_text, encoding="utf-8")
    (run / "agent_a").mkdir()
    (run / "agent_a" / "proposal.json").write_text(proposal_text, encoding="utf-8")
    review = {
        "overall_status": "FIX",
        "issues": [{
            "change_path": "Dots/Topic.md",
            "issue_type": "link",
            "severity": "medium",
            "explanation": "Unresolved wikilink: [[Missing]]",
            "proposed_correction": "Use a verified canonical target or remove the link",
            "source_pages": [],
            "evidence_refs": [],
            "corrected_content": None,
        }],
        "reviewed_changes": [{
            "change_path": "Dots/Topic.md",
            "status": "FIX",
            "checks": [],
            "issue_indices": [0],
        }],
        "global_review": None,
        "rejected_global_issues": [],
    }
    (run / "agent_b").mkdir()
    (run / "agent_b" / "review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    return run, vault


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reconcile_parser_accepts_run_vault_and_optional_decisions():
    args = build_parser().parse_args([
        "reconcile", "--run", "staging/run_1", "--vault", "vault", "--decisions", "decisions.json"
    ])

    assert args.command == "reconcile"
    assert args.run == Path("staging/run_1")
    assert args.vault == Path("vault")
    assert args.decisions == Path("decisions.json")


def test_reconcile_rejects_run_inside_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    run = vault / "run_1"
    run.mkdir()

    with pytest.raises(SystemExit):
        main(["reconcile", "--run", str(run), "--vault", str(vault)])


def test_reconcile_rejects_non_object_decision_json(tmp_path: Path):
    run, vault = reconciliation_fixture(tmp_path)
    decisions = tmp_path / "decisions.json"
    decisions.write_text('["HR-001", "DEFER"]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        main(["reconcile", "--run", str(run), "--vault", str(vault),
              "--decisions", str(decisions)])


def test_reconcile_cli_runs_pending_then_resolved_without_mutating_inputs(tmp_path: Path, capsys):
    run, vault = reconciliation_fixture(tmp_path)
    watched = [run / "proposal.json", run / "agent_a" / "proposal.json", run / "agent_b" / "review.json"]
    before = {path: sha256(path) for path in watched}

    assert main(["reconcile", "--run", str(run), "--vault", str(vault)]) == 0
    pending_output = capsys.readouterr().out
    assert "PENDING_HUMAN_REVIEW" in pending_output
    assert str(run / "reconciliation" / "HUMAN_REVIEW.md") in pending_output

    decisions = tmp_path / "decisions.json"
    decisions.write_text('{"HR-001": "DEFER"}\n', encoding="utf-8")
    assert main(["reconcile", "--run", str(run), "--vault", str(vault),
                 "--decisions", str(decisions)]) == 0
    resolved_output = capsys.readouterr().out
    assert "READY_FOR_WRITE" in resolved_output
    assert str(run / "reconciliation" / "WRITE_PREVIEW.md") in resolved_output
    assert {path: sha256(path) for path in watched} == before
    assert list(vault.rglob("*")) == []
