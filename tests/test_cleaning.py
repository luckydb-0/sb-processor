from sb_processor.cleaning import DocumentCleaner
from sb_processor.extraction import ExtractedBlock, ExtractedDocument, ExtractedPage


def page(number, body, footer=None, footer_y=92, header=None):
    blocks = [ExtractedBlock(text=body, bbox=(10, 30, 90, 70))]
    if header:
        blocks.append(ExtractedBlock(text=header, bbox=(10, 2, 90, 7)))
    if footer:
        blocks.append(ExtractedBlock(text=footer, bbox=(10, footer_y, 90, footer_y + 4)))
    return ExtractedPage(page_number=number, width=100, height=100,
                         raw_text="\n".join(block.text for block in blocks), blocks=blocks)


def document(pages):
    return ExtractedDocument(source="slides.pdf", extractor="pymupdf", page_count=len(pages), pages=pages)


def test_repeated_footer_and_page_counters_are_removed_with_audit():
    pages = [page(i, f"Unique content {i}", f"Course   -  Intro\n{i} / 4") for i in range(1, 5)]
    cleaned = DocumentCleaner().clean(document(pages))
    assert "Course" not in cleaned.cleaned_markdown()
    assert "1 / 4" not in cleaned.cleaned_markdown()
    assert "[Page 4]" in cleaned.cleaned_markdown()
    assert all(p.blocks[-1].discard_reason == "repeated_footer" for p in cleaned.pages)
    assert "Course" in cleaned.raw_markdown()


def test_near_duplicate_header_with_whitespace_hyphen_variation():
    headers = ["Machine Learning - Introduction", "Machine  Learning – Introduction",
               "machine learning-introduction", "Machine Learning — Introduction"]
    cleaned = DocumentCleaner().clean(document([page(i, f"Unique {i}", header=headers[i-1]) for i in range(1, 5)]))
    assert all(p.blocks[1].discard_reason == "repeated_header" for p in cleaned.pages)


def test_repeated_text_at_different_positions_is_kept():
    pages = [page(i, f"Topic {i}", "Shared phrase", footer_y=30 + i * 12) for i in range(1, 5)]
    cleaned = DocumentCleaner().clean(document(pages))
    assert all(p.blocks[-1].keep for p in cleaned.pages)


def test_repeated_navigation_suppresses_later_page_but_preserves_provenance():
    agenda = "Agenda\n1. Overview\n2. Methods\n3. Evaluation\n4. Examples"
    pages = [page(1, agenda), page(2, "Unique method detail"), page(3, agenda), page(4, "Unique conclusion")]
    cleaned = DocumentCleaner().clean(document(pages))
    assert cleaned.pages[0].include_in_llm_context
    assert not cleaned.pages[2].include_in_llm_context
    assert cleaned.pages[2].suppression_reason == "repeated_navigation"
    assert "[Page 3]" in cleaned.raw_markdown()
    assert "[Page 3]" not in cleaned.cleaned_markdown()
    assert "Unique conclusion" in cleaned.cleaned_markdown()


def test_repeated_short_section_title_is_retained():
    cleaned = DocumentCleaner().clean(document([page(i, "Introduction") for i in range(1, 4)]))
    assert all(p.include_in_llm_context for p in cleaned.pages)


def test_marked_layout_footer_is_removed_from_markdown():
    pages = []
    for i in range(1, 4):
        item = page(i, f"Unique content {i}", "CourseFooter")
        item.raw_text = f"Unique content {i}\n<mark>Course Footer</mark>"
        pages.append(item)
    cleaned = DocumentCleaner().clean(document(pages))
    assert "Course Footer" not in cleaned.cleaned_markdown()
    assert "Unique content 3" in cleaned.cleaned_markdown()


def test_near_duplicate_outline_with_section_change_is_suppressed():
    outline = "1 General information 2 Introduction to Machine Learning 3 Examples 4 Tasks 5 Software 6 Data Sets 20 32 42 49"
    first = page(1, "General information\n" + outline)
    second = page(2, "Unique detail")
    third = page(3, "Introduction to Machine Learning\n" + outline)
    cleaned = DocumentCleaner().clean(document([first, second, third]))
    assert cleaned.pages[0].include_in_llm_context
    assert cleaned.pages[2].suppression_reason == "repeated_navigation"


def section_page(number, section, title):
    blocks = [ExtractedBlock(text=f"{section}\n{title}", bbox=(10, 2, 90, 40)),
              ExtractedBlock(text=f"Body for slide {number}.", bbox=(10, 50, 90, 75))]
    return ExtractedPage(page_number=number, width=100, height=100,
                         raw_text="\n".join(block.text for block in blocks), blocks=blocks)


def test_consecutive_running_section_is_emitted_once_and_keeps_slide_titles():
    section = "Introduction to Machine Learning"
    source = document([section_page(i, section, f"Distinct title {i}") for i in range(1, 4)])
    clean = DocumentCleaner().clean(source)
    text = clean.cleaned_markdown()
    assert text.count(f"[Section: {section}]") == 1
    assert all(page.section_title == section for page in clean.pages)
    assert all(f"[Page {i}]\nDistinct title {i}" in text for i in range(1, 4))
    assert source.pages[0].raw_text.startswith(section)
    assert clean.pages[0].cleaning_actions[0].kind == "running_section_consolidated"


def test_sparse_repeated_top_text_is_not_a_running_section():
    pages = [section_page(1, "Shared label", "First"), page(2, "Interlude"),
             section_page(3, "Shared label", "Second"), page(4, "Different"),
             section_page(5, "Shared label", "Third")]
    clean = DocumentCleaner().clean(document(pages))
    assert all(page.section_title is None for page in clean.pages)
    assert clean.cleaned_markdown().count("Shared label") == 3


def test_running_section_transition_and_same_named_slide_title():
    pages = [section_page(i, "First section", f"Title {i}") for i in range(1, 4)]
    pages += [section_page(i, "Second section", "Second section" if i == 4 else f"Title {i}") for i in range(4, 7)]
    clean = DocumentCleaner().clean(document(pages))
    text = clean.cleaned_markdown()
    assert text.count("[Section: First section]") == 1
    assert text.count("[Section: Second section]") == 1
    assert "[Page 4]\nSecond section" in text
    assert clean.pages[3].section_title == "Second section"
