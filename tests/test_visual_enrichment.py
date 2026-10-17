from types import SimpleNamespace

import pymupdf

from sb_processor.extraction import (
    CompletenessStatus, ExtractedDocument, ExtractedPage, VisualPageContent, VisualProcessingStatus,
)
from sb_processor.visual import OpenAIVisualPageExtractor, VisualPageContext, enrich_visual_pages


def fixture(tmp_path):
    source = tmp_path / "lecture.pdf"
    pdf = pymupdf.open()
    for number in range(1, 4):
        pdf.new_page().insert_text((72, 72), f"Slide {number}")
    pdf.save(source)
    pdf.close()
    pages = [ExtractedPage(page_number=number, raw_text=f"Slide {number}", cleaned_text=f"Slide {number}",
                           requires_visual_processing=number in (1, 3), visual_flags=["large_image_area"] if number in (1, 3) else [])
             for number in range(1, 4)]
    return source, ExtractedDocument(source=str(source), extractor="pymupdf", page_count=3, pages=pages)


class FakeExtractor:
    cache_identity = "fake-v1"

    def __init__(self, fail_page=None):
        self.calls = []
        self.fail_page = fail_page

    def extract(self, image, context):
        assert image.startswith(b"\x89PNG")
        self.calls.append(context.page_number)
        if context.page_number == self.fail_page:
            raise TimeoutError("simulated")
        return VisualPageContent(additional_information=f"Diagram on original page {context.page_number}")


def test_only_flagged_pages_rendered_and_enriched_with_original_numbers(tmp_path):
    source, document = fixture(tmp_path)
    extractor = FakeExtractor()
    result, stats = enrich_visual_pages(document, source, extractor, tmp_path / "cache")
    assert extractor.calls == [1, 3]
    assert stats.flagged_pages == [1, 3]
    assert stats.api_calls == 2
    assert stats.render_scale == 2.0
    assert stats.extractor_identity == "fake-v1"
    assert result.completeness.status == CompletenessStatus.COMPLETE
    assert result.pages[1].visual_processing_status == VisualProcessingStatus.NOT_REQUIRED
    assert result.pages[2].visual_content.additional_information == "Diagram on original page 3"
    assert document.pages[0].visual_content is None


def test_cache_avoids_repeated_model_calls(tmp_path):
    source, document = fixture(tmp_path)
    first = FakeExtractor()
    enrich_visual_pages(document, source, first, tmp_path / "cache")
    second = FakeExtractor()
    result, stats = enrich_visual_pages(document, source, second, tmp_path / "cache")
    assert second.calls == []
    assert stats.cache_hits == 2 and stats.api_calls == 0
    assert result.completeness.status == CompletenessStatus.COMPLETE


def test_invalid_cache_is_recomputed(tmp_path):
    source, document = fixture(tmp_path)
    enrich_visual_pages(document, source, FakeExtractor(), tmp_path / "cache")
    next((tmp_path / "cache").glob("*.json")).write_text("broken", encoding="utf-8")
    extractor = FakeExtractor()
    result, stats = enrich_visual_pages(document, source, extractor, tmp_path / "cache")
    assert len(extractor.calls) == 1
    assert stats.cache_hits == 1 and stats.api_calls == 1
    assert result.completeness.status == CompletenessStatus.COMPLETE


def test_failure_or_no_extractor_keeps_document_partial(tmp_path):
    source, document = fixture(tmp_path)
    result, stats = enrich_visual_pages(document, source, FakeExtractor(fail_page=3), tmp_path / "cache")
    assert stats.failures == 1
    assert result.completeness.unprocessed_visual_pages == [3]
    assert result.pages[2].visual_error == "TimeoutError"
    assert result.completeness.status == CompletenessStatus.PARTIAL
    pending, _ = enrich_visual_pages(document, source, None, tmp_path / "cache2")
    assert pending.completeness.unprocessed_visual_pages == [1, 3]


def test_ambiguous_or_empty_visual_result_remains_unresolved(tmp_path):
    source, document = fixture(tmp_path)

    class AmbiguousExtractor(FakeExtractor):
        def extract(self, image, context):
            return VisualPageContent(additional_information="Possible arrow", uncertain=context.page_number == 1)

    result, stats = enrich_visual_pages(document, source, AmbiguousExtractor(), tmp_path / "cache")
    assert result.completeness.unprocessed_visual_pages == [1]
    assert result.pages[0].visual_error == "ambiguous_visual_result"
    assert stats.failures == 1


def test_openai_adapter_sends_one_image_and_local_context_only():
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=VisualPageContent(
            additional_information="Arrow from A to B"))

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    adapter = OpenAIVisualPageExtractor(client=client)
    context = VisualPageContext(page_number=13, document_title="lecture", section_title="Introduction",
                                extracted_text="A B", visual_flags=["large_image_area"])
    result = adapter.extract(b"\x89PNGfixture", context)
    assert result.additional_information == "Arrow from A to B"
    assert calls[0]["input"][1]["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert '"page_number":13' in calls[0]["input"][1]["content"][0]["text"]
    assert calls[0]["store"] is False
