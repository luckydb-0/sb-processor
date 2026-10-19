"""University review instructions and original-PDF visual evidence."""

from __future__ import annotations

import base64
from pathlib import Path

import pymupdf

from ..agent_b_context import AgentBRequest, ReviewArtifacts, build_review_request
from ..models import NoteChange


class UniversityReviewAdapter:
    def instructions(self, vault: Path) -> str:
        return (vault / "+ Inbox" / "Agent B - University Processing Review Instructions.md").read_text(encoding="utf-8")

    def build_request(self, artifacts: ReviewArtifacts, change: NoteChange,
                      instructions: str) -> AgentBRequest:
        return build_review_request(artifacts, change, instructions,
                                    max_pages=60 if change.note_type == "lecture" else 8)

    def visual_images(self, source: Path, request: AgentBRequest) -> list[tuple[int, str]]:
        numbers = [page.page_number for page in request.source_evidence
                   if page.visual_extraction and page.visual_status == "COMPLETE"]
        if not numbers or not source.is_file() or source.suffix.lower() != ".pdf":
            return []
        output = []
        with pymupdf.open(source) as document:
            for number in numbers:
                if number < 1 or number > len(document):
                    continue
                png = document[number - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).tobytes("png")
                output.append((number, "data:image/png;base64," + base64.b64encode(png).decode("ascii")))
        return output
