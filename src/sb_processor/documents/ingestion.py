"""PDF ingestion and inspectable artifacts, independent of source workflows."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .cleaning import DocumentCleaner
from .extraction import ExtractedDocument, ExtractorName, extract_document
from .visual import VisualPageExtractor, VisualRunStats, enrich_visual_pages


def ingest_pdf(source: Path, extractor: ExtractorName = "pymupdf", *,
               visual_extractor: VisualPageExtractor | None = None,
               cache_dir: Path = Path(".data/visual_cache"),
               extract_fn: Callable[[Path, ExtractorName], ExtractedDocument] = extract_document,
               ) -> tuple[ExtractedDocument, VisualRunStats]:
    raw = extract_fn(Path(source), extractor)
    cleaned = DocumentCleaner().clean(raw)
    return enrich_visual_pages(cleaned, Path(source), visual_extractor, cache_dir)


def stage_ingestion(document: ExtractedDocument, stats: VisualRunStats, output_root: Path) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run = Path(output_root) / f"ingest_{run_id}"
    run.mkdir(parents=True)
    (run / "document.json").write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (run / "text_raw.md").write_text(document.raw_markdown() + "\n", encoding="utf-8")
    (run / "text_clean.md").write_text(document.cleaned_markdown() + "\n", encoding="utf-8")
    (run / "agent_context.md").write_text(document.agent_markdown() + "\n", encoding="utf-8")
    summary = {
        "source": document.source,
        "page_count": document.page_count,
        "completeness": document.completeness.model_dump(mode="json"),
        "visual_stats": stats.model_dump(mode="json"),
        "text_characters": len(document.cleaned_markdown()),
        "text_words": len(document.cleaned_markdown().split()),
        "visual_characters": sum(len(page.visual_content.additional_information)
                                 for page in document.pages if page.visual_content),
        "visual_words": sum(len(page.visual_content.additional_information.split())
                            for page in document.pages if page.visual_content),
        "visual_pages": [{"page_number": page.page_number, "flags": page.visual_flags,
                          "text": page.cleaned_text, "visual_content": page.visual_content.model_dump(mode="json")
                          if page.visual_content else None, "status": page.visual_processing_status.value,
                          "error": page.visual_error}
                         for page in document.pages if page.requires_visual_processing],
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return run
