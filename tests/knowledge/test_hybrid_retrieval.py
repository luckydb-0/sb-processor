from sb_processor.knowledge.registry import Registry
from sb_processor.knowledge.retrieval import RetrievalPolicy, retrieve_candidate
from sb_processor.knowledge.semantic import SemanticHit
from sb_processor.knowledge.vault import scan_vault


class SemanticStub:
    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def search(self, query, *, limit):
        self.queries.append(query)
        return self.hits.get(query, [])


def note(vault, path, body):
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def fixture(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Machine Learning.md", "# Machine Learning\nExact body")
    note(vault, "Dots/Principal Component Analysis.md", "---\naliases: [PCA]\n---\n# Principal Component Analysis\nAlias body")
    note(vault, "Dots/Dataset.md", "# Dataset\nVariant body")
    note(vault, "Dots/Cross-Validation.md", "# Cross-Validation\nRelated body")
    note(vault, "Dots/K-Fold Cross-Validation.md", "# K-Fold Cross-Validation\nDistinct body")
    note(vault, "Maps/Dataset.md", "# Dataset\nWrong type")
    note(vault, "Dots/README Dataset.md", "# Dataset\nWrong file")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    return registry, RetrievalPolicy(roots={"concept": "Dots", "map": "Maps"})


def test_exact_alias_and_variant_survive_semantic_ranking(tmp_path):
    registry, policy = fixture(tmp_path)
    semantic = SemanticStub({"Machine Learning": [SemanticHit("Dots/Dataset.md", .99)],
                             "PCA": [SemanticHit("Dots/Dataset.md", .99)],
                             "Data Set": [SemanticHit("Dots/Cross-Validation.md", .99)]})
    exact = retrieve_candidate(registry, "Machine Learning", [], policy, semantic, top_k=1, threshold=.5)
    alias = retrieve_candidate(registry, "PCA", [], policy, semantic, top_k=1, threshold=.5)
    variant = retrieve_candidate(registry, "Data Set", [], policy, semantic, top_k=1, threshold=.5)
    assert exact.candidates[0].path == "Dots/Machine Learning.md"
    assert exact.candidates[0].match_kind == "exact_title"
    assert alias.candidates[0].path == "Dots/Principal Component Analysis.md"
    assert alias.candidates[0].match_kind == "alias"
    assert variant.candidates[0].path == "Dots/Dataset.md"
    assert "normalized_variant" in variant.candidates[0].retrieval_methods
    assert "Dots/Dataset.md" in variant.loaded_bodies


def test_semantic_is_evidence_not_merge_and_filters_wrong_types(tmp_path):
    registry, policy = fixture(tmp_path)
    semantic = SemanticStub({"K-Fold Cross-Validation": [
        SemanticHit("Dots/Cross-Validation.md", .88), SemanticHit("Maps/Dataset.md", .99),
        SemanticHit("Dots/README Dataset.md", .97)]})
    result = retrieve_candidate(registry, "K-Fold Cross-Validation", [], policy, semantic, top_k=3, threshold=.7)
    assert result.candidates[0].path == "Dots/K-Fold Cross-Validation.md"
    assert result.candidates[1].path == "Dots/Cross-Validation.md"
    assert result.candidates[1].semantic_score == .88
    assert all(c.note_type == "concept" for c in result.candidates)
    assert all("README" not in c.path for c in result.candidates)
    assert len(result.loaded_bodies) == 2
    assert result.semantic_query_count == 1
    assert not hasattr(result, "action")


def test_candidate_search_has_independent_top_k(tmp_path):
    registry, policy = fixture(tmp_path)
    semantic = SemanticStub({})
    first = retrieve_candidate(registry, "Machine Learning", [], policy, semantic, top_k=1)
    second = retrieve_candidate(registry, "Data Set", [], policy, semantic, top_k=1)
    assert list(first.loaded_bodies) == ["Dots/Machine Learning.md"]
    assert list(second.loaded_bodies) == ["Dots/Dataset.md"]
