"""Conservative, auditable removal of repeated PDF boilerplate."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from .extraction import ExtractedBlock, ExtractedDocument, ExtractedPage

COUNTER = re.compile(r"^\s*\d+\s*[/|–-]\s*\d+\s*$")
NAVIGATION = re.compile(r"\b(agenda|outline|contents|overview|roadmap|course structure|table of contents)\b", re.I)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("–", "-").replace("—", "-")
    text = re.sub(r"\b\d+\s*[/|\-]\s*\d+\b", " pagecounter ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    # Numbered slide titles are content. Only slash-style page counters were
    # normalized by `normalize`; other differing numbers must not be merged.
    if re.findall(r"\b\d+\b", a) != re.findall(r"\b\d+\b", b):
        return False
    if len(a) < 12 or len(b) < 12:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.9


def _zone(page: ExtractedPage, block: ExtractedBlock) -> str | None:
    if not block.bbox or not page.height:
        return None
    top, bottom = block.bbox[1] / page.height, block.bbox[3] / page.height
    if bottom <= 0.12:
        return "header"
    if top >= 0.86:
        return "footer"
    return None


def _counter_at_edge(page: ExtractedPage, block: ExtractedBlock) -> bool:
    if not block.bbox or not page.width or not page.height:
        return False
    return _zone(page, block) is not None or block.bbox[0] / page.width >= 0.90


def _remove_block_lines(text: str, removed: list[ExtractedBlock]) -> str:
    rejected = Counter(normalize(line) for block in removed for line in block.text.splitlines() if line.strip())
    compact_rejected = Counter(re.sub(r"[^\w]", "", key) for key, count in rejected.items() for _ in range(count))
    result = []
    for line in text.splitlines():
        key = normalize(re.sub(r"</?mark>", "", line, flags=re.I))
        if key and rejected[key]:
            rejected[key] -= 1
            compact_rejected[re.sub(r"[^\w]", "", key)] -= 1
            continue
        compact = re.sub(r"[^\w]", "", key)
        matched = next((candidate for candidate, count in compact_rejected.items()
                        if count and len(candidate) >= 4 and candidate == compact), None)
        if matched:
            compact_rejected[matched] -= 1
            continue
        result.append(line)
    return "\n".join(result).strip()


def _is_navigation(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or len(text.split()) < 8:
        return False
    list_lines = sum(bool(re.match(r"^(?:[-*•]|\d+[.)])\s", line)) for line in lines)
    number_count = len(re.findall(r"\b\d{1,3}\b", text))
    return bool(NAVIGATION.search(" ".join(lines[:2]))) or list_lines >= 4 or (number_count >= 5 and len(text.split()) >= 15)


def _navigation_similar(a: str, b: str) -> bool:
    if _similar(a, b):
        return True
    left, right = set(a.split()), set(b.split())
    shared = left & right
    return len(shared) >= 12 and len(shared) / len(left | right) >= 0.75


class DocumentCleaner:
    """Return a copy: raw text/blocks and original page numbers remain available."""

    def clean(self, document: ExtractedDocument) -> ExtractedDocument:
        result = document.model_copy(deep=True)
        pages = result.pages
        threshold = max(3, math.ceil(len(pages) * 0.35))
        candidates: list[tuple[ExtractedPage, ExtractedBlock, str, str, float]] = []
        for page in pages:
            for block in page.blocks:
                zone = _zone(page, block)
                if zone and len(normalize(block.text)) >= 8:
                    midpoint = (block.bbox[1] + block.bbox[3]) / (2 * page.height)
                    candidates.append((page, block, zone, normalize(block.text), midpoint))

        for page in pages:
            removed = []
            for block in page.blocks:
                if COUNTER.fullmatch(block.text.strip()) and _counter_at_edge(page, block):
                    block.keep, block.discard_reason = False, "page_counter"
                else:
                    match = next((item for item in candidates if item[1] is block), None)
                    if match:
                        _, _, zone, key, position = match
                        seen = {other_page.page_number for other_page, _, other_zone, other_key, other_position in candidates
                                if other_zone == zone and abs(other_position - position) <= 0.06
                                and _similar(key, other_key)}
                        if len(seen) >= threshold:
                            block.keep, block.discard_reason = False, f"repeated_{zone}"
                if not block.keep:
                    removed.append(block)
            page.cleaned_text = _remove_block_lines(page.raw_text, removed)

        previous: list[tuple[int, str]] = []
        for page in pages:
            text = page.cleaned_text or ""
            key = normalize(text)
            if _is_navigation(text) and any(_navigation_similar(key, old) for _, old in previous):
                page.include_in_llm_context = False
                page.suppression_reason = "repeated_navigation"
            if _is_navigation(text):
                previous.append((page.page_number, key))
        return result
