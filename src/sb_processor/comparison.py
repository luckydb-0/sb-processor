"""Local extractor comparison artifacts; no LLM calls or vault writes."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .cleaning import DocumentCleaner
from .extraction import ExtractedDocument, extract_document

log = logging.getLogger(__name__)


def _metrics(document: ExtractedDocument) -> dict:
    raw = document.raw_markdown()
    cleaned = document.cleaned_markdown()
    block_clean_chars = sum(len(page.cleaned_text or "") for page in document.pages)
    raw_content_chars = sum(len(page.raw_text) for page in document.pages)
    clean_content_chars = sum(len(page.cleaned_text or "") for page in document.pages if page.include_in_llm_context)
    header_reduction = raw_content_chars - block_clean_chars
    navigation_reduction = block_clean_chars - clean_content_chars
    marker_reduction = (len(raw) - len(cleaned)) - header_reduction - navigation_reduction
    reasons = Counter(block.discard_reason for page in document.pages for block in page.blocks if not block.keep)
    return {
        "raw_characters": len(raw), "raw_words": len(raw.split()),
        "clean_characters": len(cleaned), "clean_words": len(cleaned.split()),
        "character_reduction": len(raw) - len(cleaned),
        "word_reduction": len(raw.split()) - len(cleaned.split()),
        "character_reduction_percent": round(100 * (len(raw) - len(cleaned)) / len(raw), 2) if raw else 0,
        "estimated_raw_tokens": round(len(raw) / 4), "estimated_clean_tokens": round(len(cleaned) / 4),
        "pages_in_source": document.page_count,
        "pages_with_raw_content": sum(bool(page.raw_text.strip()) for page in document.pages),
        "pages_in_clean_context": sum(bool((page.cleaned_text or "").strip()) and page.include_in_llm_context for page in document.pages),
        "explicit_page_markers_raw": len(re.findall(r"^\[Page \d+\]$", raw, re.M)),
        "headings_raw": len(re.findall(r"^#{1,6}\s", raw, re.M)),
        "tables_raw": len(re.findall(r"^\s*\|.+\|\s*$", raw, re.M)),
        "positioned_blocks": sum(block.bbox is not None for page in document.pages for block in page.blocks),
        "pages_rejected_by_extractor": [page.page_number for page in document.pages if page.metadata.get("anydoc_page_rejected")],
        "removed_blocks": sum(reasons.values()), "removed_by_reason": dict(reasons),
        "repeated_navigation_pages_suppressed": sum(page.suppression_reason == "repeated_navigation" for page in document.pages),
        "reduction_characters_by_stage": {
            "headers_footers_page_counters": header_reduction,
            "repeated_navigation": navigation_reduction,
            "other_deterministic": marker_reduction,
        },
    }


def compare_pdf_extractors(source: Path, output_root: Path) -> Path:
    source = Path(source).resolve(strict=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run = Path(output_root) / f"compare_{run_id}"
    run.mkdir(parents=True)
    results = {}
    report = ["# Cleaning report", "", f"Source: `{source}`", ""]
    cleaner = DocumentCleaner()
    for extractor in ("pymupdf", "anydoc", "pymupdf4llm"):
        raw = extract_document(source, extractor)
        clean = cleaner.clean(raw)
        (run / f"{extractor}_raw.md").write_text(raw.raw_markdown() + "\n", encoding="utf-8")
        (run / f"{extractor}_clean.md").write_text(clean.cleaned_markdown() + "\n", encoding="utf-8")
        (run / f"{extractor}_document.json").write_text(clean.model_dump_json(indent=2) + "\n", encoding="utf-8")
        # Keep the original whole-document AnyDoc output separately: its
        # Markdown cannot be mapped reliably back to source pages.
        if extractor == "anydoc":
            from .pdf import extract_pdf
            whole = extract_pdf(source, "anydoc")
            (run / "anydoc_whole_document.md").write_text(whole.rstrip() + "\n", encoding="utf-8")
            (run / "anydoc.md").write_text(whole.rstrip() + "\n", encoding="utf-8")
            results[extractor] = _metrics(clean)
            results[extractor]["whole_document_characters"] = len(whole)
            results[extractor]["whole_document_words"] = len(whole.split())
            results[extractor]["whole_document_page_provenance"] = False
        elif extractor == "pymupdf":
            (run / f"{extractor}.md").write_text(raw.raw_markdown() + "\n", encoding="utf-8")
            results[extractor] = _metrics(clean)
        else:
            results[extractor] = _metrics(clean)
        report += [f"## {extractor}", ""]
        for page in clean.pages:
            removed = [block for block in page.blocks if not block.keep]
            if removed or page.suppression_reason:
                report.append(f"### Page {page.page_number}")
                for block in removed:
                    report.append(f"- {block.discard_reason}: {block.text!r} (bbox: {block.bbox})")
                if page.suppression_reason:
                    report.append(f"- suppressed: {page.suppression_reason}")
                report.append("")
    (run / "cleaning_report.md").write_text("\n".join(report), encoding="utf-8")
    comparison = {"source": str(source), "extractors": results,
                  "token_estimate_method": "characters / 4; approximate, not model tokenizer counts"}
    (run / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    lines = ["# PDF extraction comparison", "", f"Source: `{source}`", "",
             "| Extractor | Raw words | Clean words | Reduction | Pages raw / clean | Explicit page markers | Markdown headings | Table lines | Removed blocks | Navigation pages |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, m in results.items():
        raw_file = f"{name}.md" if name in ("pymupdf", "anydoc") else f"{name}_raw.md"
        lines.append(f"| [{name}]({raw_file}) | {m['raw_words']} | {m['clean_words']} | {m['character_reduction_percent']}% | "
                     f"{m['pages_with_raw_content']} / {m['pages_in_clean_context']} | {m['explicit_page_markers_raw']} | {m['headings_raw']} | "
                     f"{m['tables_raw']} | {m['removed_blocks']} | {m['repeated_navigation_pages_suppressed']} |")
    lines += ["", "Each raw/clean Markdown file uses `[Page N]` markers. `*_document.json` retains page metadata, raw text, "
              "block positions and cleaning decisions. Counts are diagnostic; inspect reading order, tables, equations, and visuals manually.", "",
              "Token estimates use characters / 4, not a model tokenizer. See `comparison.json` for stage-level savings and `cleaning_report.md` for decisions.", ""]
    (run / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    (run / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("Saved PDF extraction comparison at %s", run)
    return run
