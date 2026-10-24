import pymupdf
import sys
from types import SimpleNamespace

from sb_processor.documents.extraction import DoclingExtractor, extract_document


def test_raw_extraction_preserves_numbered_pages_and_positions(tmp_path):
    source = tmp_path / "slides.pdf"
    document = pymupdf.open()
    for title in ("First slide", "Second slide"):
        document.new_page().insert_text((72, 72), title)
    document.save(source)
    document.close()

    result = extract_document(source, "pymupdf")
    assert [page.page_number for page in result.pages] == [1, 2]
    assert result.page_count == 2
    assert result.pages[0].blocks[0].bbox is not None
    assert "[Page 2]" in result.raw_markdown()
    assert "Second slide" in result.raw_markdown()


def test_raw_extraction_preserves_line_positions_for_reflow(tmp_path):
    source = tmp_path / "wrapped.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "A long source line\nA continuation")
    document.save(source)
    document.close()
    result = extract_document(source, "pymupdf")
    assert len(result.pages[0].blocks[0].line_bboxes) == 2
    assert result.pages[0].blocks[0].line_bboxes[0][1] < result.pages[0].blocks[0].line_bboxes[1][1]


def test_raw_extraction_records_image_area_for_visual_detection(tmp_path):
    source = tmp_path / "diagram.pdf"
    document = pymupdf.open()
    page = document.new_page(width=100, height=100)
    page.insert_text((10, 15), "Diagram")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
    pixmap.clear_with(0xFFFFFF)
    page.insert_image(pymupdf.Rect(10, 20, 90, 90), pixmap=pixmap)
    document.save(source)
    document.close()
    result = extract_document(source, "pymupdf")
    assert result.pages[0].metadata["visual_features"]["image_area_ratio"] > 0.5


def test_layout_extraction_keeps_markdown_and_layout_metadata(tmp_path):
    source = tmp_path / "slides.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "A slide title")
    document.save(source)
    document.close()

    result = extract_document(source, "pymupdf4llm")
    assert result.pages[0].page_number == 1
    assert result.pages[0].blocks
    assert result.pages[0].blocks[0].bbox is not None
    assert "A slide title" in result.pages[0].raw_text


def test_anydoc_page_rejection_uses_audited_raw_fallback(tmp_path, monkeypatch):
    source = tmp_path / "slides.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "First slide")
    document.new_page().insert_text((72, 72), "Visual slide caption")
    document.save(source)
    document.close()

    class UnsupportedError(Exception):
        pass

    class NeedsOcrError(Exception):
        pass

    calls = []

    def convert(data, format, *, ocr):
        calls.append((format, ocr))
        if len(calls) == 2:
            raise UnsupportedError("PDF has no extractable text")
        return "# First slide"

    monkeypatch.setitem(sys.modules, "anydoc", SimpleNamespace(to_markdown_bytes=convert,
                            UnsupportedError=UnsupportedError, NeedsOcrError=NeedsOcrError))
    result = extract_document(source, "anydoc")
    assert len(calls) == 2
    assert result.pages[1].metadata["fallback_extractor"] == "pymupdf"
    assert "Visual slide caption" in result.pages[1].raw_text
    assert result.pages[1].blocks[0].bbox is not None


def test_docling_preserves_pages_tables_pictures_and_visual_gate(tmp_path, monkeypatch):
    source = tmp_path / "slides.pdf"
    pdf = pymupdf.open()
    pdf.new_page(width=200, height=100).insert_text((10, 20), "First page")
    second = pdf.new_page(width=200, height=100)
    second.insert_text((10, 20), "Second page")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
    pixmap.clear_with(0xFFFFFF)
    second.insert_image(pymupdf.Rect(10, 30, 190, 95), pixmap=pixmap)
    pdf.save(source)
    pdf.close()

    class Box:
        def to_top_left_origin(self, height):
            assert height == 100
            return SimpleNamespace(l=10, t=15, r=70, b=30)

    table = SimpleNamespace(label=SimpleNamespace(value="table"), text=None,
                            prov=[SimpleNamespace(page_no=2, bbox=Box())],
                            export_to_markdown=lambda doc: "| A | B |\n|---|---|\n| 1 | 2 |")
    picture = SimpleNamespace(label=SimpleNamespace(value="picture"), text=None,
                              prov=[SimpleNamespace(page_no=2, bbox=Box())])
    heading = SimpleNamespace(label=SimpleNamespace(value="section_header"), text="First page",
                              prov=[SimpleNamespace(page_no=1, bbox=Box())])

    class FakeDocument:
        def export_to_markdown(self, *, page_no, image_placeholder):
            assert image_placeholder == ""
            return "# First page" if page_no == 1 else "| A | B |\n|---|---|\n| 1 | 2 |"

        def iterate_items(self, *, page_no):
            return iter((item, 0) for item in ([heading] if page_no == 1 else [table, picture]))

    monkeypatch.setattr(DoclingExtractor, "_convert", lambda self, path:
                        SimpleNamespace(status=SimpleNamespace(value="success"), document=FakeDocument()))
    result = extract_document(source, "docling")
    assert [page.page_number for page in result.pages] == [1, 2]
    assert result.pages[1].metadata["docling_item_counts"] == {"table": 1, "picture": 1}
    assert result.pages[1].metadata["docling_pictures"] == [{"bbox": (10, 15, 70, 30)}]
    assert result.pages[1].blocks[0].bbox == (10, 15, 70, 30)
    assert result.pages[1].blocks[0].block_type == "table"
    assert "[Page 2]" in result.agent_markdown()
    assert "| 1 | 2 |" in result.agent_markdown()
    from sb_processor.documents.cleaning import DocumentCleaner
    cleaned = DocumentCleaner().clean(result)
    assert cleaned.completeness.status.value == "PARTIAL"
    assert cleaned.completeness.unprocessed_visual_pages == [2]
    assert "[Page 2]" in cleaned.agent_markdown()
    assert "VISUAL CONTENT: UNRESOLVED" in cleaned.agent_markdown()


def test_docling_rejects_incomplete_conversion(tmp_path, monkeypatch):
    source = tmp_path / "slides.pdf"
    source.write_bytes(b"%PDF")
    monkeypatch.setattr(DoclingExtractor, "_convert", lambda self, path:
                        SimpleNamespace(status=SimpleNamespace(value="partial"), document=None))
    import pytest
    with pytest.raises(ValueError, match="did not complete"):
        extract_document(source, "docling")
