from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from ..pdf import PdfExtractor, extract_pdf


class UniversityWorkflow:
    name = "university"

    def __init__(self, *, rules_path: Path | None = None, templates_path: Path | None = None, instructions_path: Path | None = None, pdf_extractor: PdfExtractor = "pymupdf"):
        self.rules_path = rules_path
        self.templates_path = templates_path
        self.instructions_path = instructions_path
        self.pdf_extractor = pdf_extractor

    def prepare(self, source: Path, vault: Path) -> dict[str, Any]:
        source = Path(source)
        if source.suffix.lower() != ".pdf":
            raise ValueError("University workflow currently accepts one PDF source")
        locations = {
            "rules": self.rules_path or vault / "+ Inbox" / "University Material Processing Rules.md",
            "templates": self.templates_path or vault / "+ Inbox" / "University Templates.md",
            "instructions": self.instructions_path or vault / "+ Inbox" / "Agent A - University Compact Processing Instructions.md",
        }
        inputs = {}
        for name, path in locations.items():
            try:
                inputs[name] = Path(path).read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"University {name} file missing: {path}; pass --{name}") from exc
        source_text = extract_pdf(source, self.pdf_extractor)
        prompt = files("sb_processor").joinpath("prompts/university.md").read_text(encoding="utf-8")
        knowledge_root = vault / "Atlas" if (vault / "Atlas" / "Dots").is_dir() else vault
        roots = {
            "concept": (knowledge_root / "Dots").relative_to(vault).as_posix(),
            "map": (knowledge_root / "Maps").relative_to(vault).as_posix(),
            "course_and_lecture": (knowledge_root / "Sources" / "University").relative_to(vault).as_posix(),
        }
        return {"source_text": source_text, "pdf_extractor": self.pdf_extractor, "workflow_prompt": prompt, "suggested_note_roots": roots, **inputs}
