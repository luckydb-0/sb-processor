from sb_processor.registry import Registry
from sb_processor.retrieval import RetrievalPolicy, retrieve_notes
from sb_processor.vault import scan_vault


def note(vault, path, text):
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_metadata_first_retrieval_filters_and_ranks(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Machine Learning.md", "---\ntype: concept\n---\n# Machine Learning\nRelevant body")
    note(vault, "Dots/Principal Component Analysis.md", "---\ntype: concept\naliases: [PCA]\n---\n# Principal Component Analysis\nPCA body")
    note(vault, "Maps/Machine Learning.md", "---\ntype: map\n---\n# Machine Learning\nMap body")
    note(vault, "Dots/GitHub/README - Machine Learning.md", "# Machine Learning\nUnrelated body")
    note(vault, "+ Inbox/Agent A - Machine Learning.md", "# Machine Learning\nPrompt body")
    note(vault, "docs/Machine Learning.md", "# Machine Learning\nDocs body")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "Machine Learning and PCA", ["Machine Learning", "PCA"],
                            RetrievalPolicy(roots={"concept": "Dots", "map": "Maps", "course": "Sources/University", "lecture": "Sources/University"}))
    assert result.candidates[0].path == "Dots/Machine Learning.md"
    assert result.candidates[0].match_kind == "exact_title"
    assert any(c.path == "Dots/Principal Component Analysis.md" and c.match_kind == "alias" for c in result.candidates)
    assert not any(c.path == "Maps/Machine Learning.md" and c.note_type == "concept" for c in result.candidates)
    assert set(result.loaded_bodies) == {"Dots/Machine Learning.md", "Dots/Principal Component Analysis.md", "Maps/Machine Learning.md"}
    assert any(x.path.endswith("README - Machine Learning.md") and x.reason == "retrieval policy" for x in result.excluded)
    assert any(x.path.startswith("+ Inbox/") and x.reason == "retrieval policy" for x in result.excluded)
    assert any(x.path.startswith("docs/") and x.reason == "retrieval policy" for x in result.excluded)


def test_missing_candidate_is_unknown_and_does_not_load_bodies(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Unrelated.md", "---\ntype: concept\n---\n# Unrelated\nLarge body")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "Novel topic", ["Novel topic"], RetrievalPolicy(roots={"concept": "Dots"}))
    assert result.candidates == []
    assert result.loaded_bodies == {}
    assert "not proof" in result.limitation
