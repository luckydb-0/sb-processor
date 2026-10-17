"""Conservative, auditable removal of repeated PDF boilerplate."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from .extraction import CleaningAction, ExtractedBlock, ExtractedDocument, ExtractedPage

COUNTER = re.compile(r"^\s*\d+\s*[/|–-]\s*\d+\s*$")
NAVIGATION = re.compile(r"\b(agenda|outline|contents|overview|roadmap|course structure|table of contents)\b", re.I)
TYPOGRAPHY_MAP = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
    "\u00a0": " ", "\u2007": " ", "\u2009": " ", "\u202f": " ",
    "‐": "-", "‑": "-",
})


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


def _top_label(page: ExtractedPage) -> tuple[str, str | None, int] | None:
    if not page.height or not page.cleaned_text:
        return None
    for index, block in enumerate(page.blocks):
        if not block.keep or not block.text.strip() or not block.bbox:
            continue
        if block.bbox[1] / page.height > 0.035:
            return None
        lines = [line.strip() for line in block.text.splitlines() if line.strip()]
        label = lines[0]
        if len(label) < 6 or len(label) > 100 or not re.search(r"[A-Za-z]", label):
            return None
        first_clean_line = next((line.strip() for line in page.cleaned_text.splitlines() if line.strip()), "")
        if normalize(first_clean_line) != normalize(label):
            return None
        return label, lines[1] if len(lines) > 1 else None, index
    return None


def _consolidate_running_sections(pages: list[ExtractedPage]) -> None:
    labels = {i: _top_label(page) for i, page in enumerate(pages)}
    groups: list[list[int]] = []
    current: list[int] = []
    for index, candidate in labels.items():
        if candidate is None:
            continue
        if current:
            previous = current[-1]
            intervening = range(previous + 1, index)
            if (index - previous > 2 or normalize(labels[previous][0]) != normalize(candidate[0])
                    or any(labels[middle] is not None for middle in intervening)):
                groups.append(current)
                current = []
        current.append(index)
    if current:
        groups.append(current)

    for group in groups:
        if len(group) < 3 or not any(right - left == 1 for left, right in zip(group, group[1:])):
            continue
        titles = {normalize(labels[index][1]) for index in group if labels[index][1]}
        if len(titles) < 2:
            continue
        section = labels[group[0]][0]
        for index in group:
            page = pages[index]
            label, _, block_index = labels[index]
            lines = page.cleaned_text.splitlines()
            first = next((line_index for line_index, line in enumerate(lines) if line.strip()), None)
            if first is None or normalize(lines[first]) != normalize(label):
                continue
            lines.pop(first)
            page.cleaned_text = "\n".join(lines).strip()
            page.section_title = section
            page.cleaning_actions.append(CleaningAction(kind="running_section_consolidated", before=label,
                                                        after="", block_index=block_index))


def _normalize_clean_typography(page: ExtractedPage) -> None:
    if page.cleaned_text is None:
        return
    lines = []
    in_code = False
    for line in page.cleaned_text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            lines.append(line)
            continue
        changed = line if in_code else line.translate(TYPOGRAPHY_MAP)
        if not in_code and not line.lstrip().startswith("|") and not line.startswith("    "):
            changed = re.sub(r"(?<=\S)[ \t]{2,}", " ", changed)
        if changed != line:
            page.cleaning_actions.append(CleaningAction(kind="unicode_normalized", before=line, after=changed))
        lines.append(changed)
    page.cleaned_text = "\n".join(lines)


def _protected_reflow_line(line: str) -> bool:
    value = line.strip()
    return (not value or bool(re.match(r"^(?:#{1,6}\s|[-*•▶]\s?|\d+[.)]\s|\||```|~~~)", value))
            or bool(re.search(r"[=≤≥∑∫]|\s[+−*/]\s", value)))


def _should_join_lines(previous: str, following: str, left: tuple[float, ...],
                       right: tuple[float, ...], page_width: float) -> bool:
    if _protected_reflow_line(previous) or _protected_reflow_line(following):
        return False
    if len(previous.strip()) < 45 or previous.rstrip().endswith((".", "?", "!", ":", ";", "-")):
        return False
    if (left[2] - left[0]) / page_width < 0.60 or not re.match(r"^[a-z]", following.lstrip()):
        return False
    indent = abs(left[0] - right[0])
    return indent <= 4 or (previous.lstrip().startswith("⇒") and 0 <= right[0] - left[0] <= 25)


def _reflow_page(page: ExtractedPage) -> None:
    if not page.cleaned_text or not page.width or not page.height:
        return
    for block_index, block in enumerate(page.blocks):
        if not block.keep or block.block_type != "text" or not block.bbox or block.bbox[1] / page.height < 0.17:
            continue
        lines = block.text.splitlines()
        if len(lines) < 2 or len(lines) != len(block.line_bboxes) or block.text.strip() not in page.cleaned_text:
            continue
        if any(line.lstrip().startswith(("```", "~~~")) or line.startswith("    ") for line in lines):
            continue
        result = [lines[0]]
        changes = []
        for index in range(1, len(lines)):
            previous, following = lines[index - 1], lines[index]
            if _should_join_lines(previous, following, block.line_bboxes[index - 1],
                                  block.line_bboxes[index], page.width):
                result[-1] += " " + following.lstrip()
                changes.append(CleaningAction(kind="paragraph_reflow", before=previous + "\n" + following,
                                              after=previous.rstrip() + " " + following.lstrip(), block_index=block_index))
            else:
                result.append(following)
        if changes:
            page.cleaned_text = page.cleaned_text.replace(block.text.strip(), "\n".join(result), 1)
            page.cleaning_actions.extend(changes)


def _flag_visual_page(page: ExtractedPage) -> None:
    features = page.metadata.get("visual_features")
    if not features:
        return
    image_heavy = features.get("image_area_ratio", 0) >= 0.15 and features.get("text_characters", 0) <= 300
    vector_heavy = features.get("large_drawing_area_ratio", 0) >= 0.35 and features.get("text_characters", 0) <= 200
    if image_heavy or vector_heavy:
        page.requires_visual_processing = True
        page.visual_flags = ["low_text_density"]
        if image_heavy:
            page.visual_flags.append("large_image_area")
        if vector_heavy:
            page.visual_flags.append("large_vector_area")


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
            page.metadata["cleaning_stage_characters"] = {"after_boilerplate": len(page.cleaned_text)}

        previous: list[tuple[int, str]] = []
        for page in pages:
            text = page.cleaned_text or ""
            key = normalize(text)
            if _is_navigation(text) and any(_navigation_similar(key, old) for _, old in previous):
                page.include_in_llm_context = False
                page.suppression_reason = "repeated_navigation"
            if _is_navigation(text):
                previous.append((page.page_number, key))
        _consolidate_running_sections(pages)
        for page in pages:
            stages = page.metadata["cleaning_stage_characters"]
            stages["after_sections"] = len(page.cleaned_text or "")
            _reflow_page(page)
            stages["after_reflow"] = len(page.cleaned_text or "")
            _normalize_clean_typography(page)
            stages["after_typography"] = len(page.cleaned_text or "")
            _flag_visual_page(page)
        return result
