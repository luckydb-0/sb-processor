"""Disposable local vector index of global Concept Notes.

Qdrant stores vectors and vault-relative identities; the vault remains the source of truth.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .registry import Registry
from .retrieval import RetrievalPolicy


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REPRESENTATION_VERSION = 1


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class FastEmbedder:
    """Local ONNX embedding; no remote inference calls."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL, cache_dir: Path | None = None):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir) if cache_dir else None)
        self.dimension = self._model.embedding_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


def concept_representation(title: str, aliases: list[str], body: str, *, body_chars: int = 1800) -> str:
    """Lead with identity, then a bounded start of the body to avoid long-note dilution."""
    return f"Title: {title}\nAliases: {', '.join(aliases)}\n{body[:body_chars]}"


@dataclass(frozen=True)
class SyncStats:
    model: str
    indexed: int
    embedded: int
    reused: int
    updated: int
    deleted: int
    elapsed_seconds: float


@dataclass(frozen=True)
class SemanticHit:
    path: str
    score: float


class SemanticIndex:
    def __init__(self, path: Path, *, embedder: Embedder | None = None,
                 model_name: str = DEFAULT_EMBEDDING_MODEL, model_cache: Path | None = None):
        from qdrant_client import QdrantClient, models

        self._models = models
        self.embedder = embedder or FastEmbedder(model_name, model_cache)
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection = "concept_" + hashlib.sha256(
            f"{self.embedder.model_name}:{REPRESENTATION_VERSION}".encode()).hexdigest()[:16]
        self.client = QdrantClient(path=str(self.path))
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=self.embedder.dimension, distance=models.Distance.COSINE))

    def __enter__(self) -> "SemanticIndex":
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _id(path: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "second-brain:" + path))

    def _existing(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        offset = None
        while True:
            page, offset = self.client.scroll(self.collection, limit=256, offset=offset, with_payload=True)
            for item in page:
                if item.payload and item.payload.get("path"):
                    result[item.payload["path"]] = item.payload
            if offset is None:
                break
        return result

    def sync(self, registry: Registry, policy: RetrievalPolicy) -> SyncStats:
        start = time.monotonic()
        eligible = {note.path: note for note in registry.metadata() if policy.kind(note) == "concept"}
        existing = self._existing()
        pending = []
        updated = 0
        for path, meta in eligible.items():
            old = existing.get(path)
            if old and old.get("content_hash") == meta.content_hash:
                continue
            note = registry.get(path)
            if note is None:
                continue
            pending.append((meta, concept_representation(meta.title, meta.aliases, note.body)))
            if old:
                updated += 1
        if pending:
            vectors = self.embedder.embed([item[1] for item in pending])
            self.client.upsert(self.collection, points=[self._models.PointStruct(
                id=self._id(meta.path), vector=vector,
                payload={"path": meta.path, "title": meta.title, "aliases": meta.aliases,
                         "note_type": "concept", "content_hash": meta.content_hash})
                for (meta, _), vector in zip(pending, vectors, strict=True)])
        deleted_paths = set(existing) - set(eligible)
        if deleted_paths:
            self.client.delete(self.collection, points_selector=[self._id(path) for path in deleted_paths])
        return SyncStats(model=self.embedder.model_name, indexed=len(eligible), embedded=len(pending),
                         reused=len(eligible)-len(pending), updated=updated, deleted=len(deleted_paths),
                         elapsed_seconds=round(time.monotonic()-start, 3))

    def search(self, query: str, *, limit: int = 5) -> list[SemanticHit]:
        if not query.strip():
            return []
        vector = self.embedder.embed([query])[0]
        response = self.client.query_points(self.collection, query=vector, limit=limit, with_payload=True)
        return [SemanticHit(path=hit.payload["path"], score=hit.score)
                for hit in response.points if hit.payload and hit.payload.get("path")]
