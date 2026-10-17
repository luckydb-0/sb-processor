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
    assert default.visual_model == "gpt-4o"


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
