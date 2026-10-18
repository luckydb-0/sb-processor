"""Policy-aware, metadata-first retrieval for Agent A workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .models import CandidateMatch, NoteMetadata
from .registry import Registry, lexical_tokens, normalize


@dataclass(frozen=True)
class RetrievalPolicy:
    roots: dict[str, str]
    excluded_segments: frozenset[str] = frozenset({"docs", "prompts", "staging", "config", "debug", ".git"})
    excluded_name_fragments: tuple[str, ...] = ("readme", "agent a", "agent b", "processing instruction", "processing rules", "config", "technical debt", "todo")
    body_limits: dict[str, int] = field(default_factory=lambda: {"concept": 4, "map": 2, "course": 2, "lecture": 2})
    max_candidates: int = 30
    max_body_chars: int = 20_000
    max_total_body_chars: int = 40_000

    def kind(self, note: NoteMetadata) -> str | None:
        parts = note.path.casefold().split("/")
        filename = note.filename.casefold()
        if any(part in self.excluded_segments for part in parts[:-1]) or any(fragment in filename for fragment in self.excluded_name_fragments):
            return None
        for kind, root in self.roots.items():
            prefix = root.strip("/").casefold() + "/"
            if not note.path.casefold().startswith(prefix):
                continue
            if kind == "concept" and "/github/" in note.path.casefold():
                return None
            declared = note.note_type.casefold() if note.note_type else None
            if declared and declared != kind:
                continue
            if kind == "course" and "/lectures/" in note.path.casefold():
                continue
            if kind == "lecture" and "/lectures/" not in note.path.casefold() and declared != "lecture":
                continue
            return kind
        return None


@dataclass(frozen=True)
class ExcludedNote:
    path: str
    reason: str


@dataclass
class RetrievalResult:
    candidates: list[CandidateMatch]
    loaded_bodies: dict[str, str]
    excluded: list[ExcludedNote]
    considered: int
    limitation: str = "No deterministic match is not proof that no equivalent note exists."
    skipped_bodies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticObservation:
    path: str
    score: float
    above_threshold: bool


@dataclass
class CandidateRetrieval(RetrievalResult):
    candidate_name: str = ""
    semantic_observations: list[SemanticObservation] = field(default_factory=list)


class SemanticSearcher(Protocol):
    def search(self, query: str, *, limit: int) -> list:
        ...


def _phrase_present(phrase: str, source_norm: str) -> bool:
    key = normalize(phrase)
    return bool(key and re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", source_norm))


def _map_canonical(value: str) -> str:
    key = normalize(value.removesuffix(".md"))
    return key.removesuffix(" map").strip()


def _compact(value: str) -> str:
    return normalize(value).replace(" ", "")


def _match(note: NoteMetadata, queries: list[str], source_norm: str, kind: str) -> tuple[str, float] | None:
    names = [note.title, note.filename.removesuffix(".md"), *note.aliases]
    best: tuple[str, float] | None = None
    for query in queries:
        key = normalize(query)
        if not key:
            continue
        if key == normalize(note.title):
            match = ("exact_title", 1.0)
        elif key == normalize(note.filename) or key == normalize(note.filename.removesuffix(".md")):
            match = ("exact_filename", 0.99)
        elif any(key == normalize(alias) for alias in note.aliases):
            match = ("alias", 0.98)
        elif len(key) >= 5 and any(_compact(query) == _compact(name) for name in names):
            match = ("normalized_variant", 0.96)
        elif kind == "map" and _map_canonical(query) in {_map_canonical(note.title), _map_canonical(note.filename)}:
            match = ("canonical_name", 0.97)
        else:
            qwords = lexical_tokens(query)
            nwords = lexical_tokens(" ".join(names))
            overlap = len(qwords & nwords)
            if not overlap or overlap / max(len(qwords), 1) < 0.5:
                continue
            match = ("lexical", 0.3 + 0.4 * overlap / len(qwords | nwords))
        if best is None or match[1] > best[1]:
            best = match
    if best:
        return best
    if any(_phrase_present(alias, source_norm) for alias in note.aliases if len(normalize(alias)) >= 3):
        return "alias_mention", 0.85
    if any(_phrase_present(name, source_norm) for name in names[:2] if len(normalize(name)) >= 3):
        return "source_mention", 0.75
    return None


def retrieve_notes(registry: Registry, source_text: str, candidate_terms: list[str], policy: RetrievalPolicy,
                   *, load_bodies: bool = True) -> RetrievalResult:
    """Filter metadata, rank names/aliases, then load only bounded full bodies."""
    source_norm = normalize(source_text)
    candidates: list[CandidateMatch] = []
    excluded: list[ExcludedNote] = []
    considered = 0
    for note in registry.metadata():
        kind = policy.kind(note)
        if kind is None:
            excluded.append(ExcludedNote(note.path, "retrieval policy"))
            continue
        considered += 1
        match = _match(note, candidate_terms, source_norm, kind)
        if match is None:
            continue
        candidates.append(CandidateMatch(path=note.path, filename=note.filename, title=note.title, note_type=kind,
                                         aliases=note.aliases, maps=note.maps, match_kind=match[0], score=match[1]))
    type_order = {"concept": 0, "course": 1, "lecture": 2, "map": 3}
    candidates.sort(key=lambda c: (-c.score, type_order.get(c.note_type or "", 9), c.path))
    candidates = candidates[:policy.max_candidates]
    loaded_bodies: dict[str, str] = {}
    skipped_bodies: list[str] = []
    counts: dict[str, int] = {}
    total_body_chars = 0
    for candidate in candidates if load_bodies else []:
        kind = candidate.note_type or ""
        if counts.get(kind, 0) >= policy.body_limits.get(kind, 0):
            continue
        note = registry.get(candidate.path)
        if note is None:
            continue
        if len(note.body) > policy.max_body_chars or total_body_chars + len(note.body) > policy.max_total_body_chars:
            skipped_bodies.append(candidate.path)
            continue
        loaded_bodies[candidate.path] = note.body
        total_body_chars += len(note.body)
        counts[kind] = counts.get(kind, 0) + 1
    return RetrievalResult(candidates, loaded_bodies, excluded, considered, skipped_bodies=skipped_bodies)


def retrieve_candidate(registry: Registry, name: str, aliases: list[str], policy: RetrievalPolicy,
                       semantic: SemanticSearcher | None = None, *, note_type: str = "concept",
                       top_k: int = 4, threshold: float = 0.55) -> CandidateRetrieval:
    """Retrieve a small evidence set for one discovery candidate, independently of all others."""
    if top_k < 1 or not 0 <= threshold <= 1:
        raise ValueError("top_k must be positive and threshold must be between 0 and 1")
    metadata = registry.metadata()
    allowed = {n.path: n for n in metadata if policy.kind(n) == note_type}
    excluded = [ExcludedNote(n.path, "retrieval policy or wrong note type") for n in metadata if n.path not in allowed]
    hits: dict[str, CandidateMatch] = {}
    for note in allowed.values():
        match = _match(note, [name, *aliases], "", note_type)
        if match is None:
            continue
        kind, score = match
        hits[note.path] = CandidateMatch(path=note.path, filename=note.filename, title=note.title,
                                         note_type=note_type, aliases=note.aliases, maps=note.maps,
                                         match_kind=kind, score=score, retrieval_methods=[kind],
                                         lexical_score=score if kind == "lexical" else None)
    observations = []
    if note_type == "concept" and semantic is not None:
        for query in list(dict.fromkeys([name, *aliases]))[:3]:
            for result in semantic.search(query, limit=max(top_k * 3, 10)):
                observations.append(SemanticObservation(result.path, result.score, result.score >= threshold))
                note = allowed.get(result.path)
                if note is None or result.score < threshold:
                    continue
                if result.path not in hits:
                    hits[result.path] = CandidateMatch(path=note.path, filename=note.filename, title=note.title,
                        note_type=note_type, aliases=note.aliases, maps=note.maps, match_kind="semantic",
                        score=result.score, retrieval_methods=["semantic"], semantic_score=result.score)
                else:
                    hit = hits[result.path]
                    hit.semantic_score = max(hit.semantic_score or 0, result.score)
                    if "semantic" not in hit.retrieval_methods:
                        hit.retrieval_methods.append("semantic")
    priority = {"exact_title": 0, "exact_filename": 1, "alias": 2, "canonical_name": 2,
                "normalized_variant": 3, "lexical": 4, "semantic": 5}
    ordered = sorted(hits.values(), key=lambda hit: (priority.get(hit.match_kind, 9), -hit.score, hit.path))
    strong = [hit for hit in ordered if priority.get(hit.match_kind, 9) <= 2]
    selected = strong + [hit for hit in ordered if hit not in strong][:max(0, top_k-len(strong))]
    loaded: dict[str, str] = {}
    skipped: list[str] = []
    for hit in selected:
        note = registry.get(hit.path)
        if note is None:
            continue
        if len(note.body) > policy.max_body_chars:
            skipped.append(hit.path)
        else:
            loaded[hit.path] = note.body
    return CandidateRetrieval(candidates=selected, loaded_bodies=loaded, excluded=excluded,
                              considered=len(allowed), skipped_bodies=skipped,
                              candidate_name=name, semantic_observations=observations)


def source_candidate_terms(source_text: str, source_name: str) -> list[str]:
    """Use short page headings and the source name; no LLM call or full-body note search."""
    terms = [source_name.removesuffix(".pdf").replace("-", " ").replace("_", " ")]
    for line in source_text.splitlines():
        value = line.strip().lstrip("# ").strip()
        if not value or value in {"TEXT:", "VISUAL CONTENT:"} or value.startswith("[Page "):
            continue
        if (line.startswith("#") or (len(value) <= 90 and value.endswith(":"))) and 2 <= len(value) <= 90:
            terms.append(value.rstrip(":"))
        if len(terms) >= 40:
            break
    return list(dict.fromkeys(terms))
