import pymupdf

from sb_processor.extraction import extract_document


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
