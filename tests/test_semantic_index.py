from sb_processor.registry import Registry
from sb_processor.retrieval import RetrievalPolicy
from sb_processor.semantic import SemanticIndex, concept_representation
from sb_processor.vault import scan_vault


class FakeEmbedder:
    model_name = "fixture-multilingual"
    dimension = 3

    def __init__(self):
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        vectors = []
        for text in texts:
            text = text.casefold()
            vectors.append([1.0 if "dataset" in text or "insieme di dati" in text else 0.0,
                            1.0 if "validation" in text else 0.0,
                            1.0 if "classification" in text else 0.0])
        return vectors


def note(vault, path, body):
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_semantic_index_filters_and_incrementally_syncs(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Dataset.md", "---\naliases: [Data Set]\n---\n# Dataset\nA collection of examples")
    note(vault, "Maps/Dataset.md", "# Dataset\nA collection of examples")
    note(vault, "Dots/README Dataset.md", "# Dataset\nUnrelated")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    embedder = FakeEmbedder()
    policy = RetrievalPolicy(roots={"concept": "Dots", "map": "Maps"})
    with SemanticIndex(tmp_path / "vectors", embedder=embedder) as index:
        first = index.sync(registry, policy)
        assert (first.indexed, first.embedded, first.reused, first.updated) == (1, 1, 0, 0)
        assert index.search("insieme di dati", limit=3)[0].path == "Dots/Dataset.md"
    with SemanticIndex(tmp_path / "vectors", embedder=embedder) as index:
        second = index.sync(registry, policy)
        assert (second.indexed, second.embedded, second.reused) == (1, 0, 1)
        note(vault, "Dots/Dataset.md", "# Dataset\nUpdated definition")
        registry.rebuild(scan_vault(vault))
        third = index.sync(registry, policy)
        assert (third.embedded, third.updated) == (1, 1)
        (vault / "Dots/Dataset.md").unlink()
        registry.rebuild(scan_vault(vault))
        fourth = index.sync(registry, policy)
        assert fourth.deleted == 1
        assert index.search("dataset", limit=3) == []


def test_representation_prioritizes_identity_and_truncates_body():
    value = concept_representation("Dataset", ["Data Set"], "X" * 5000, body_chars=100)
    assert value.startswith("Title: Dataset\nAliases: Data Set\n")
    assert len(value) < 150
