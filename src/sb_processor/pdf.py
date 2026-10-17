"""Local PDF extraction options shared by source workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import pymupdf

log = logging.getLogger(__name__)
PdfExtractor = Literal["pymupdf", "anydoc", "pymupdf4llm"]
MAX_SOURCE_CHARS = 120_000


def extract_pdf(source: Path, extractor: PdfExtractor = "pymupdf") -> str:
    """Return local PDF text/Markdown for model context; never run hosted OCR."""
    source = Path(source)
    if source.suffix.lower() != ".pdf":
        raise ValueError("PDF extraction requires a .pdf source")
    if extractor == "pymupdf":
        pages = []
        with pymupdf.open(source) as document:
            for index, page in enumerate(document, 1):
                content = page.get_text("text").strip()
                if content:
                    pages.append(f"[Page {index}]\n{content}")
        result = "\n\n".join(pages)
    elif extractor == "anydoc":
        try:
            import anydoc
        except ImportError as exc:
            raise RuntimeError("anydoc Python binding is missing; install the firecrawl-anydoc extra in this Python environment") from exc
        try:
            result = anydoc.to_markdown(source, ocr="reject")
        except anydoc.NeedsOcrError as exc:
            raise ValueError("PDF needs OCR; anydoc hosted OCR is disabled in this PoC") from exc
    elif extractor == "pymupdf4llm":
        from .extraction import extract_document
        result = extract_document(source, extractor).raw_markdown()
    else:
        raise ValueError(f"Unknown PDF extractor: {extractor}")
    if not result.strip():
        raise ValueError("PDF has no extractable text; OCR is outside this PoC")
    if len(result) > MAX_SOURCE_CHARS:
        raise ValueError(f"PDF extracted text exceeds {MAX_SOURCE_CHARS:,} characters; split the source before processing")
    log.info("Extracted %d characters from %s using %s", len(result), source, extractor)
    return result


def compare_pdf_extractors(source: Path, output_root: Path) -> Path:
    """Save raw/clean conversions and provenance reports without an LLM call."""
    from .comparison import compare_pdf_extractors as compare
    return compare(source, output_root)
