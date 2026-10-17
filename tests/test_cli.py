from sb_processor.cli import build_parser, main
import pytest


def test_process_accepts_pdf_extractor_selection():
    args = build_parser().parse_args(["process", "--workflow", "university", "--source", "lecture.pdf", "--vault", "vault", "--pdf-extractor", "anydoc"])
    assert args.pdf_extractor == "anydoc"


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
