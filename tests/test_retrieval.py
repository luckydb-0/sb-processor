from sb_processor.knowledge.registry import Registry
from sb_processor.knowledge.retrieval import RetrievalPolicy, retrieve_notes
from sb_processor.knowledge.vault import scan_vault


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
    note(vault, "config/Machine Learning.md", "# Machine Learning\nConfiguration body")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "Machine Learning and PCA", ["Machine Learning", "PCA"],
                            RetrievalPolicy(roots={"concept": "Dots", "map": "Maps", "course": "Sources/University", "lecture": "Sources/University"}))
    assert result.candidates[0].path == "Dots/Machine Learning.md"
    assert result.candidates[0].match_kind == "exact_title"
    assert any(c.path == "Dots/Principal Component Analysis.md" and c.match_kind == "alias" for c in result.candidates)
    filename_result = retrieve_notes(registry, "", ["Principal Component Analysis.md"],
                                     RetrievalPolicy(roots={"concept": "Dots"}), load_bodies=False)
    assert filename_result.candidates[0].match_kind == "exact_filename"
    assert not any(c.path == "Maps/Machine Learning.md" and c.note_type == "concept" for c in result.candidates)
    assert set(result.loaded_bodies) == {"Dots/Machine Learning.md", "Dots/Principal Component Analysis.md", "Maps/Machine Learning.md"}
    assert any(x.path.endswith("README - Machine Learning.md") and x.reason == "retrieval policy" for x in result.excluded)
    assert any(x.path.startswith("+ Inbox/") and x.reason == "retrieval policy" for x in result.excluded)
    assert any(x.path.startswith("docs/") and x.reason == "retrieval policy" for x in result.excluded)
    assert any(x.path.startswith("config/") and x.reason == "retrieval policy" for x in result.excluded)


def test_missing_candidate_is_unknown_and_does_not_load_bodies(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Unrelated.md", "---\ntype: concept\n---\n# Unrelated\nLarge body")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "Novel topic", ["Novel topic"], RetrievalPolicy(roots={"concept": "Dots"}))
    assert result.candidates == []
    assert result.loaded_bodies == {}
    assert "not proof" in result.limitation


def test_oversized_note_body_stays_metadata_only(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Machine Learning.md", "# Machine Learning\n" + "x" * 200)
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "Machine Learning", ["Machine Learning"],
                            RetrievalPolicy(roots={"concept": "Dots"}, max_body_chars=100))
    assert [c.path for c in result.candidates] == ["Dots/Machine Learning.md"]
    assert result.loaded_bodies == {}
    assert result.skipped_bodies == ["Dots/Machine Learning.md"]


def test_alias_mention_gets_body_before_loose_title_mentions(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Dots/Machine Learning.md", "# Machine Learning\nBody")
    note(vault, "Dots/Predictive Classification.md", "---\ntype: concept\naliases: [Classification]\n---\n# Predictive Classification\nBody")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "Machine Learning and Classification", [],
                            RetrievalPolicy(roots={"concept": "Dots"}, body_limits={"concept": 1}))
    assert result.candidates[0].path == "Dots/Predictive Classification.md"
    assert result.candidates[0].match_kind == "alias_mention"
    assert list(result.loaded_bodies) == ["Dots/Predictive Classification.md"]


def test_map_suffix_resolves_to_existing_canonical_map(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Maps/Machine Learning.md", "---\ntype: map\n---\n# Machine Learning\nMap body")
    note(vault, "Dots/Machine Learning.md", "---\ntype: concept\n---\n# Machine Learning\nConcept body")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    result = retrieve_notes(registry, "", ["Machine Learning - Map"],
                            RetrievalPolicy(roots={"map": "Maps", "concept": "Dots"}), load_bodies=False)
    assert result.candidates[0].path == "Maps/Machine Learning.md"
    assert result.candidates[0].match_kind == "canonical_name"
