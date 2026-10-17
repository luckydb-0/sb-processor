import sys
import json
from types import SimpleNamespace

import pymupdf
import pytest

from sb_processor.pdf import compare_pdf_extractors, extract_pdf


def make_pdf(path):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Principal Component Analysis")
    document.save(path)
    document.close()


def test_anydoc_extractor_uses_local_markdown_conversion(tmp_path, monkeypatch):
    pdf = tmp_path / "lecture.pdf"
    pdf.write_bytes(b"fixture")
    calls = []

    def to_markdown(path, *, ocr):
        calls.append((path, ocr))
        return "# Lecture\n\nA definition.\n"

    monkeypatch.setitem(sys.modules, "anydoc", SimpleNamespace(to_markdown=to_markdown))
    assert extract_pdf(pdf, "anydoc") == "# Lecture\n\nA definition.\n"
    assert calls == [(pdf, "reject")]


def test_anydoc_extractor_reports_missing_install(tmp_path, monkeypatch):
    pdf = tmp_path / "lecture.pdf"
    pdf.write_bytes(b"fixture")
    monkeypatch.setitem(sys.modules, "anydoc", None)
    with pytest.raises(RuntimeError, match="firecrawl-anydoc"):
        extract_pdf(pdf, "anydoc")


def test_comparison_writes_both_extractions_without_llm(tmp_path):
    pytest.importorskip("anydoc")
    pdf = tmp_path / "lecture.pdf"
    make_pdf(pdf)
    output = compare_pdf_extractors(pdf, tmp_path / "comparison")
    assert "Principal Component Analysis" in (output / "pymupdf.md").read_text()
    assert "Principal Component Analysis" in (output / "anydoc.md").read_text()
    assert "pymupdf.md" in (output / "summary.md").read_text()
    assert "anydoc.md" in (output / "summary.md").read_text()
    assert "Explicit page markers" in (output / "summary.md").read_text()
    assert "Markdown headings" in (output / "summary.md").read_text()
    assert "Principal Component Analysis" in (output / "pymupdf_clean.md").read_text()
    assert "Principal Component Analysis" in (output / "pymupdf4llm_raw.md").read_text()
    assert (output / "anydoc_whole_document.md").exists()
    assert (output / "cleaning_report.md").exists()
    comparison = json.loads((output / "comparison.json").read_text())
    assert comparison["extractors"]["pymupdf4llm"]["pages_in_source"] == 1
    assert comparison["extractors"]["anydoc"]["whole_document_page_provenance"] is False


def test_anydoc_rejects_textless_pdf(tmp_path):
    pytest.importorskip("anydoc")
    pdf = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(pdf)
    document.close()
    with pytest.raises(ValueError, match="OCR"):
        extract_pdf(pdf, "anydoc")
