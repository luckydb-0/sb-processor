from sb_processor.cleaning import DocumentCleaner
from sb_processor.comparison import _metrics
from sb_processor.extraction import ExtractedBlock, ExtractedDocument, ExtractedPage


def test_comparison_metrics_audit_sections_transforms_and_visual_flags():
    pages = []
    for number in range(1, 4):
        heading = f"Running section\nSlide {number}"
        content = "oﬃcial   summary" if number == 2 else f"Body text {number}"
        pages.append(ExtractedPage(page_number=number, raw_text=heading + "\n" + content,
                                   width=100, height=100,
                                   blocks=[ExtractedBlock(text=heading, bbox=(10, 2, 90, 40)),
                                           ExtractedBlock(text=content, bbox=(10, 50, 90, 65))],
                                   metadata={"visual_features": {"text_characters": 30,
                                                                 "image_area_ratio": 0.5 if number == 2 else 0,
                                                                 "large_drawing_area_ratio": 0}}))
    source = ExtractedDocument(source="fixture.pdf", extractor="pymupdf", page_count=3, pages=pages)
    metrics = _metrics(DocumentCleaner().clean(source))
    assert metrics["running_section_repetitions_consolidated"] == 3
    assert metrics["unicode_normalizations"] == 1
    assert metrics["paragraph_reflows"] == 0
    assert [item["page_number"] for item in metrics["visual_pages"]] == [2]
    assert metrics["sections"][0]["title"] == "Running section"
    assert sum(metrics["reduction_characters_by_stage"].values()) == metrics["character_reduction"]
