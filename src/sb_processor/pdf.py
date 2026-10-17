"""Local PDF extraction options shared by source workflows."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pymupdf

log = logging.getLogger(__name__)
PdfExtractor = Literal["pymupdf", "anydoc"]
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
    else:
        raise ValueError(f"Unknown PDF extractor: {extractor}")
    if not result.strip():
        raise ValueError("PDF has no extractable text; OCR is outside this PoC")
    if len(result) > MAX_SOURCE_CHARS:
        raise ValueError(f"PDF extracted text exceeds {MAX_SOURCE_CHARS:,} characters; split the source before processing")
    log.info("Extracted %d characters from %s using %s", len(result), source, extractor)
    return result


def compare_pdf_extractors(source: Path, output_root: Path) -> Path:
    """Save both raw conversions and simple measurements, without an LLM call."""
    source = Path(source).resolve(strict=True)
    outputs = {}
    for extractor in ("pymupdf", "anydoc"):
        outputs[extractor] = extract_pdf(source, extractor)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run = Path(output_root) / f"compare_{run_id}"
    run.mkdir(parents=True)
    for extractor, content in outputs.items():
        (run / f"{extractor}.md").write_text(content.rstrip() + "\n", encoding="utf-8")
    lines = [
        "# PDF extraction comparison", "", f"Source: `{source}`", "",
        "| Extractor | Output | Characters | Words | Explicit page markers | Markdown headings |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for extractor, content in outputs.items():
        pages = len(re.findall(r"^\[Page \d+\]$", content, re.MULTILINE))
        headings = len(re.findall(r"^#{1,6} ", content, re.MULTILINE))
        lines.append(f"| {extractor} | [{extractor}.md]({extractor}.md) | {len(content)} | {len(content.split())} | {pages} | {headings} |")
    lines += ["", "Inspect both Markdown files for headings, equations, tables, reading order, and source references. Marker counts describe the output format, not extraction quality.", ""]
    (run / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("Saved PDF extraction comparison at %s", run)
    return run
