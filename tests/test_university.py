import pymupdf
import pytest

from sb_processor.workflows.university import UniversityWorkflow
from sb_processor.extraction import ExtractedDocument, ExtractedPage


def test_university_workflow_extracts_pdf_and_external_rules(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "+ Inbox"
    inbox.mkdir(parents=True)
    (inbox / "University Material Processing Rules.md").write_text("Full rules", encoding="utf-8")
    (inbox / "University Templates.md").write_text("Templates", encoding="utf-8")
    (inbox / "Agent A - University Compact Processing Instructions.md").write_text("Compact instructions", encoding="utf-8")
    pdf = tmp_path / "lecture.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Principal Component Analysis")
    document.save(pdf)
    document.close()
    context = UniversityWorkflow().prepare(pdf, vault)
    assert "Principal Component Analysis" in context["source_text"]
    assert "[Page 1]" in context["source_text"]
    assert context["rules"] == "Full rules"
    assert context["templates"] == "Templates"
    assert context["instructions"] == "Compact instructions"


def test_university_workflow_detects_atlas_note_roots(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "+ Inbox"
    inbox.mkdir(parents=True)
    for name in ("University Material Processing Rules.md", "University Templates.md", "Agent A - University Compact Processing Instructions.md"):
        (inbox / name).write_text("input", encoding="utf-8")
    (vault / "Atlas" / "Dots").mkdir(parents=True)
    (vault / "Atlas" / "Maps").mkdir(parents=True)
    (vault / "Atlas" / "Sources").mkdir(parents=True)
    pdf = tmp_path / "lecture.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Lecture content")
    document.save(pdf)
    document.close()
    context = UniversityWorkflow().prepare(pdf, vault)
    assert context["suggested_note_roots"] == {"concept": "Atlas/Dots", "map": "Atlas/Maps", "course_and_lecture": "Atlas/Sources/University"}


def test_university_workflow_rejects_textless_pdf(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "+ Inbox"
    inbox.mkdir(parents=True)
    for name in ("University Material Processing Rules.md", "University Templates.md", "Agent A - University Compact Processing Instructions.md"):
        (inbox / name).write_text("input", encoding="utf-8")
    pdf = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(pdf)
    document.close()
    with pytest.raises(ValueError, match="no extractable text"):
        UniversityWorkflow().prepare(pdf, vault)


def test_university_workflow_can_select_anydoc(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    inbox = vault / "+ Inbox"
    inbox.mkdir(parents=True)
    for name in ("University Material Processing Rules.md", "University Templates.md", "Agent A - University Compact Processing Instructions.md"):
        (inbox / name).write_text("input", encoding="utf-8")
    pdf = tmp_path / "lecture.pdf"
    pdf.write_bytes(b"fixture")
    calls = []

    def fake_extract(path, backend):
        calls.append((path, backend))
        return ExtractedDocument(source=str(path), extractor="anydoc", page_count=1,
                                 pages=[ExtractedPage(page_number=1, raw_text="# Converted lecture")])

    monkeypatch.setattr("sb_processor.workflows.university.extract_document", fake_extract)
    context = UniversityWorkflow(pdf_extractor="anydoc").prepare(pdf, vault)
    assert context["source_text"] == "[Page 1]\n# Converted lecture"
    assert context["pdf_extractor"] == "anydoc"
    assert calls == [(pdf, "anydoc")]


def test_university_context_uses_cleaned_text_with_page_provenance(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "+ Inbox"
    inbox.mkdir(parents=True)
    for name in ("University Material Processing Rules.md", "University Templates.md", "Agent A - University Compact Processing Instructions.md"):
        (inbox / name).write_text("input", encoding="utf-8")
    pdf = tmp_path / "lecture.pdf"
    document = pymupdf.open()
    for index in range(1, 5):
        slide = document.new_page()
        slide.insert_text((72, 72), f"Unique slide {index}")
        slide.insert_text((72, 780), "Repeated course footer")
    document.save(pdf)
    document.close()
    context = UniversityWorkflow().prepare(pdf, vault)
    assert "Repeated course footer" not in context["source_text"]
    assert "[Page 4]" in context["source_text"]
    assert "Unique slide 4" in context["source_text"]
