"""Replaceable, local PDF extraction with page and block provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Protocol

import pymupdf
from pydantic import BaseModel, Field

ExtractorName = Literal["pymupdf", "anydoc", "pymupdf4llm"]


class ExtractedBlock(BaseModel):
    text: str
    bbox: tuple[float, float, float, float] | None = None
    line_bboxes: list[tuple[float, float, float, float]] = Field(default_factory=list)
    block_type: str = "text"
    keep: bool = True
    discard_reason: str | None = None


class CleaningAction(BaseModel):
    kind: str
    before: str
    after: str
    block_index: int | None = None


class ExtractedPage(BaseModel):
    page_number: int = Field(ge=1)
    raw_text: str
    blocks: list[ExtractedBlock] = Field(default_factory=list)
    width: float | None = None
    height: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    cleaned_text: str | None = None
    include_in_llm_context: bool = True
    suppression_reason: str | None = None
    section_title: str | None = None
    cleaning_actions: list[CleaningAction] = Field(default_factory=list)
    requires_visual_processing: bool = False
    visual_flags: list[str] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    source: str
    extractor: ExtractorName
    page_count: int
    pages: list[ExtractedPage]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def raw_markdown(self) -> str:
        return _render(self.pages, cleaned=False)

    def cleaned_markdown(self) -> str:
        return _render(self.pages, cleaned=True)


def _render(pages: list[ExtractedPage], *, cleaned: bool) -> str:
    parts = []
    active_section = None
    for page in pages:
        if cleaned and not page.include_in_llm_context:
            continue
        content = page.cleaned_text if cleaned and page.cleaned_text is not None else page.raw_text
        if content.strip():
            if cleaned and page.section_title and page.section_title != active_section:
                parts.append(f"[Section: {page.section_title}]")
            parts.append(f"[Page {page.page_number}]\n{content.strip()}")
            active_section = page.section_title if cleaned else None
    return "\n\n".join(parts)


class DocumentExtractor(Protocol):
    def extract(self, source: Path) -> ExtractedDocument: ...


def _pymupdf_blocks(page: pymupdf.Page) -> list[ExtractedBlock]:
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        lines = ["".join(span["text"] for span in line["spans"]) for line in block.get("lines", [])]
        text = "\n".join(lines).strip()
        if not text:
            continue
        blocks.append(ExtractedBlock(text=text, bbox=tuple(block["bbox"]),
                                     line_bboxes=[tuple(line["bbox"]) for line in block["lines"]]))
    return blocks


def _visual_features(page: pymupdf.Page) -> dict[str, float | int]:
    area = page.rect.get_area()
    image_areas = [(pymupdf.Rect(image["bbox"]) & page.rect).get_area() for image in page.get_image_info()]
    drawing_ratios = [(pymupdf.Rect(drawing["rect"]) & page.rect).get_area() / area
                      for drawing in page.get_drawings()]
    # A full-page background rectangle is common in slide templates.
    meaningful_drawings = [ratio for ratio in drawing_ratios if 0.35 <= ratio <= 0.9]
    text = page.get_text("text").strip()
    return {
        "text_characters": len(text),
        "image_count": len(image_areas),
        "image_area_ratio": round(min(1.0, sum(image_areas) / area), 4),
        "largest_image_area_ratio": round(max(image_areas, default=0) / area, 4),
        "large_drawing_area_ratio": round(max(meaningful_drawings, default=0), 4),
    }


class RawPyMuPDFExtractor:
    def extract(self, source: Path) -> ExtractedDocument:
        with pymupdf.open(source) as pdf:
            pages = [ExtractedPage(page_number=index, raw_text=page.get_text("text").strip(),
                                   blocks=_pymupdf_blocks(page), width=page.rect.width, height=page.rect.height,
                                   metadata={"visual_features": _visual_features(page)})
                     for index, page in enumerate(pdf, 1)]
            return ExtractedDocument(source=str(source), extractor="pymupdf", page_count=len(pdf), pages=pages,
                                     metadata=dict(pdf.metadata))


class AnyDocExtractor:
    def extract(self, source: Path) -> ExtractedDocument:
        try:
            import anydoc
        except ImportError as exc:
            raise RuntimeError("anydoc Python binding is missing; install the firecrawl-anydoc extra in this Python environment") from exc
        pages = []
        with pymupdf.open(source) as pdf:
            for index, page in enumerate(pdf, 1):
                single = pymupdf.open()
                single.insert_pdf(pdf, from_page=index - 1, to_page=index - 1)
                fallback = False
                try:
                    text = anydoc.to_markdown_bytes(single.tobytes(), "pdf", ocr="reject")
                except anydoc.NeedsOcrError as exc:
                    raise ValueError("PDF needs OCR; anydoc hosted OCR is disabled in this PoC") from exc
                except anydoc.UnsupportedError as exc:
                    if "no extractable text" not in str(exc).lower():
                        raise
                    # Preserve page content and provenance when AnyDoc's
                    # single-page converter rejects a visual-heavy slide.
                    text = page.get_text("text")
                    fallback = True
                finally:
                    single.close()
                pages.append(ExtractedPage(page_number=index, raw_text=text.strip(),
                                           blocks=_pymupdf_blocks(page) if fallback else [],
                                           width=page.rect.width, height=page.rect.height,
                                           metadata={"block_positions_available": fallback,
                                                     "anydoc_page_rejected": fallback,
                                                     "fallback_extractor": "pymupdf" if fallback else None,
                                                     "visual_features": _visual_features(page)}))
            return ExtractedDocument(source=str(source), extractor="anydoc", page_count=len(pdf), pages=pages,
                                     metadata=dict(pdf.metadata))


class PyMuPDF4LLMExtractor:
    def extract(self, source: Path) -> ExtractedDocument:
        try:
            import pymupdf4llm
        except ImportError as exc:
            raise RuntimeError("pymupdf4llm is missing; install the layout extra") from exc
        try:
            pymupdf4llm.use_layout(True)
        except ImportError as exc:
            raise RuntimeError("pymupdf-layout is missing; install the layout extra") from exc
        # Keep headers and footers in the raw view; the cleaner makes auditable decisions.
        chunks = pymupdf4llm.to_markdown(str(source), page_chunks=True, use_ocr=False, header=True, footer=True)
        layout = json.loads(pymupdf4llm.to_json(str(source), use_ocr=False))
        layout_pages = {page["page_number"]: page for page in layout["pages"]}
        with pymupdf.open(source) as pdf:
            visual_features = {index: _visual_features(page) for index, page in enumerate(pdf, 1)}
        pages = []
        for index, chunk in enumerate(chunks, 1):
            number = chunk["metadata"].get("page_number", index)
            positioned = layout_pages[number]
            blocks = []
            for box in positioned["boxes"]:
                lines = []
                for line in box.get("textlines", []):
                    parts = []
                    previous_right = None
                    for span in line.get("spans", []):
                        left = span.get("bbox", [0])[0]
                        if previous_right is not None and left - previous_right > max(0.75, span.get("size", 8) * 0.12):
                            parts.append(" ")
                        parts.append(span["text"])
                        previous_right = span.get("bbox", [0, 0, 0])[2]
                    lines.append("".join(parts))
                blocks.append(ExtractedBlock(text="\n".join(lines).strip(),
                                             bbox=(box["x0"], box["y0"], box["x1"], box["y1"]),
                                             line_bboxes=[tuple(line["bbox"]) for line in box.get("textlines", [])],
                                             block_type=box.get("boxclass", "text")))
            pages.append(ExtractedPage(page_number=number, raw_text=chunk["text"].strip(), blocks=blocks,
                                       width=positioned["width"], height=positioned["height"],
                                       metadata={"page_boxes": chunk.get("page_boxes", []),
                                                 "toc_items": chunk.get("toc_items", []),
                                                 "full_ocred": positioned.get("full_ocred", False),
                                                 "visual_features": visual_features[number]}))
        return ExtractedDocument(source=str(source), extractor="pymupdf4llm", page_count=layout["page_count"],
                                 pages=pages, metadata={"toc": layout.get("toc", [])})


EXTRACTORS: dict[ExtractorName, DocumentExtractor] = {
    "pymupdf": RawPyMuPDFExtractor(),
    "anydoc": AnyDocExtractor(),
    "pymupdf4llm": PyMuPDF4LLMExtractor(),
}


def extract_document(source: Path, extractor: ExtractorName = "pymupdf") -> ExtractedDocument:
    source = Path(source)
    if source.suffix.lower() != ".pdf":
        raise ValueError("PDF extraction requires a .pdf source")
    try:
        result = EXTRACTORS[extractor].extract(source)
    except KeyError as exc:
        raise ValueError(f"Unknown PDF extractor: {extractor}") from exc
    if not result.raw_markdown().strip():
        raise ValueError("PDF has no extractable text; OCR is outside this PoC")
    return result
