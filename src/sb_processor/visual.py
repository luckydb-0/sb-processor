"""Selective, auditable visual extraction for detector-flagged PDF pages."""

from __future__ import annotations

import base64
import hashlib
import logging
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol

import pymupdf
from pydantic import BaseModel

from .extraction import ExtractedDocument, VisualPageContent, VisualProcessingStatus

log = logging.getLogger(__name__)
RENDER_SCALE = 1.5


class VisualPageContext(BaseModel):
    page_number: int
    document_title: str
    section_title: str | None = None
    extracted_text: str
    visual_flags: list[str]


class VisualPageExtractor(Protocol):
    @property
    def cache_identity(self) -> str: ...

    def extract(self, image: bytes, context: VisualPageContext) -> VisualPageContent: ...


class OpenAIVisualPageExtractor:
    def __init__(self, model: str = "gpt-4o-mini", client: Any = None):
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        self.client = client
        self.model = model

    @property
    def cache_identity(self) -> str:
        prompt = files("sb_processor").joinpath("prompts/visual_page.md").read_bytes()
        return f"openai:{self.model}:{hashlib.sha256(prompt).hexdigest()}"

    def extract(self, image: bytes, context: VisualPageContext) -> VisualPageContent:
        prompt = files("sb_processor").joinpath("prompts/visual_page.md").read_text(encoding="utf-8")
        image_url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": [
                    {"type": "input_text", "text": context.model_dump_json()},
                    {"type": "input_image", "image_url": image_url, "detail": "high"},
                ]},
            ],
            text_format=VisualPageContent,
            store=False,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError(f"Incomplete visual response (status={response.status})")
        return VisualPageContent.model_validate(response.output_parsed)


class VisualRunStats(BaseModel):
    flagged_pages: list[int]
    api_calls: int = 0
    cache_hits: int = 0
    failures: int = 0


def _source_hash(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enrich_visual_pages(document: ExtractedDocument, source: Path, extractor: VisualPageExtractor | None,
                        cache_dir: Path, *, render_scale: float = RENDER_SCALE) -> tuple[ExtractedDocument, VisualRunStats]:
    """Render and interpret only flagged pages; failed pages stay unresolved."""
    result = document.model_copy(deep=True)
    flagged = [page for page in result.pages if page.requires_visual_processing]
    stats = VisualRunStats(flagged_pages=[page.page_number for page in flagged])
    if not flagged:
        return result, stats
    for page in flagged:
        page.visual_processing_status = VisualProcessingStatus.PENDING
    if extractor is None:
        return result, stats

    source = Path(source)
    source_digest = _source_hash(source)
    with pymupdf.open(source) as pdf:
        for page in flagged:
            try:
                image = pdf[page.page_number - 1].get_pixmap(
                    matrix=pymupdf.Matrix(render_scale, render_scale), alpha=False
                ).tobytes("png")
                key_data = f"{source_digest}:{page.page_number}:{hashlib.sha256(image).hexdigest()}:{extractor.cache_identity}"
                cache_key = hashlib.sha256(key_data.encode()).hexdigest()
                cached = Path(cache_dir) / f"{cache_key}.json"
                cache_hit = cached.is_file()
                if cache_hit:
                    content = VisualPageContent.model_validate_json(cached.read_text(encoding="utf-8"))
                    stats.cache_hits += 1
                else:
                    context = VisualPageContext(page_number=page.page_number, document_title=source.stem,
                                                section_title=page.section_title,
                                                extracted_text=page.cleaned_text or "", visual_flags=page.visual_flags)
                    stats.api_calls += 1
                    content = extractor.extract(image, context)
                    content = VisualPageContent.model_validate(content)
                page.visual_content = content
                if content.uncertain or not content.additional_information.strip():
                    page.visual_processing_status = VisualProcessingStatus.FAILED
                    page.visual_error = "ambiguous_visual_result" if content.uncertain else "empty_visual_result"
                    stats.failures += 1
                    continue
                page.visual_processing_status = VisualProcessingStatus.COMPLETE
                page.visual_error = None
                if not cache_hit:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_text(content.model_dump_json(indent=2) + "\n", encoding="utf-8")
                log.info("Visual page %d complete (%s)", page.page_number, "cache" if cache_hit else "extractor")
            except Exception as exc:
                page.visual_processing_status = VisualProcessingStatus.FAILED
                page.visual_error = type(exc).__name__
                stats.failures += 1
                log.warning("Visual page %d failed: %s", page.page_number, type(exc).__name__)
    return result, stats
