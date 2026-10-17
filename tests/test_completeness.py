from sb_processor.extraction import (
    CompletenessStatus, ExtractedDocument, ExtractedPage, VisualPageContent,
    VisualProcessingStatus,
)


def document(*pages):
    return ExtractedDocument(source="lecture.pdf", extractor="pymupdf", page_count=len(pages), pages=list(pages))


def page(number, flagged=False, status=VisualProcessingStatus.NOT_REQUIRED):
    return ExtractedPage(page_number=number, raw_text=f"Page {number}", cleaned_text=f"Page {number}",
                         requires_visual_processing=flagged, visual_processing_status=status)


def test_no_visual_pages_are_complete():
    result = document(page(1), page(2)).completeness
    assert result.status == CompletenessStatus.COMPLETE
    assert result.visual_pages == result.unprocessed_visual_pages == []


def test_all_visual_pages_processed_are_complete():
    result = document(page(13, True, VisualProcessingStatus.COMPLETE),
                      page(14, True, VisualProcessingStatus.RESOLVED)).completeness
    assert result.status == CompletenessStatus.COMPLETE
    assert result.visual_pages_processed == [13, 14]


def test_pending_or_failed_visual_pages_remain_partial():
    result = document(page(13, True, VisualProcessingStatus.COMPLETE),
                      page(14, True, VisualProcessingStatus.FAILED))
    assert result.completeness.status == CompletenessStatus.PARTIAL
    assert result.completeness.unprocessed_visual_pages == [14]
    assert result.model_dump(mode="json")["completeness"]["unprocessed_visual_pages"] == [14]


def test_visual_content_and_provenance_survive_agent_serialization():
    enriched = page(13, True, VisualProcessingStatus.COMPLETE)
    enriched.visual_content = VisualPageContent(additional_information="An arrow links data to model")
    unresolved = page(14, True, VisualProcessingStatus.PENDING)
    result = document(enriched, unresolved)
    assert "[Page 13]\nTEXT:\nPage 13\nVISUAL CONTENT:\nAn arrow links data to model" in result.agent_markdown()
    assert "[Page 14]\nTEXT:\nPage 14\nVISUAL CONTENT: UNRESOLVED" in result.agent_markdown()
    assert result.model_dump(mode="json")["pages"][0]["page_number"] == 13
    assert result.completeness.unprocessed_visual_pages == [14]
