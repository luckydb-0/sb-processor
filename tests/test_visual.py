from sb_processor.documents.cleaning import DocumentCleaner
from sb_processor.documents.extraction import ExtractedDocument, ExtractedPage


def visual_page(number, text, *, image_area=0.0, vector_area=0.0):
    return ExtractedPage(page_number=number, raw_text=text, width=100, height=100,
                         metadata={"visual_features": {
                             "image_area_ratio": image_area,
                             "large_drawing_area_ratio": vector_area,
                             "text_characters": len(text),
                         }})


def clean(pages):
    return DocumentCleaner().clean(ExtractedDocument(source="fixture.pdf", extractor="pymupdf",
                                                     page_count=len(pages), pages=pages))


def test_image_heavy_page_with_little_text_is_flagged_with_provenance():
    source = [visual_page(1, "Ordinary introduction with enough text " * 12),
              visual_page(2, "Diagram caption", image_area=0.55)]
    result = clean(source)
    assert not result.pages[0].requires_visual_processing
    assert result.pages[1].requires_visual_processing
    assert result.pages[1].visual_flags == ["low_text_density", "large_image_area"]
    assert result.pages[1].page_number == 2
    assert "[Page 2]" in result.cleaned_markdown()


def test_text_heavy_page_with_image_and_small_illustration_are_not_flagged():
    pages = [visual_page(1, "Technical explanation " * 30, image_area=0.55),
             visual_page(2, "Short but complete caption", image_area=0.04),
             visual_page(3, "Only a title")]
    result = clean(pages)
    assert all(not page.requires_visual_processing for page in result.pages)


def test_large_vector_region_with_little_text_is_flagged():
    result = clean([visual_page(1, "Flow chart", vector_area=0.55)])
    assert result.pages[0].requires_visual_processing
    assert result.pages[0].visual_flags == ["low_text_density", "large_vector_area"]
