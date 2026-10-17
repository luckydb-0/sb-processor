from sb_processor.vault import scan_vault
from sb_processor.registry import Registry


def test_scanner_reads_frontmatter_and_missing_metadata(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "PCA.md").write_text(
        '---\ntitle: Principal Component Analysis\ntype: concept\naliases: [PCA]\nmaps: ["[[Machine Learning]]"]\n---\n# PCA\nBody.\n',
        encoding="utf-8",
    )
    (vault / "Plain.md").write_text("# Plain heading\nText", encoding="utf-8")
    notes = {n.path: n for n in scan_vault(vault)}
    assert notes["Dots/PCA.md"].title == "Principal Component Analysis"
    assert notes["Dots/PCA.md"].aliases == ["PCA"]
    assert notes["Dots/PCA.md"].maps == ["[[Machine Learning]]"]
    assert notes["Dots/PCA.md"].body == "# PCA\nBody.\n"
    assert len(notes["Dots/PCA.md"].content_hash) == 64
    assert notes["Plain.md"].title == "Plain heading"
    assert notes["Plain.md"].frontmatter == {}


def test_registry_rebuild_and_deterministic_lookup(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Principal Component Analysis.md").write_text(
        "---\ntype: concept\naliases: [PCA]\n---\n# Principal Component Analysis\nDimensionality reduction.",
        encoding="utf-8",
    )
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    assert registry.lookup("Principal Component Analysis")[0].match_kind == "exact_title"
    assert registry.lookup("Principal Component Analysis.md")[0].match_kind == "exact_filename"
    assert registry.lookup("pca")[0].match_kind == "alias"
    assert registry.lookup("component analysis")[0].match_kind == "lexical"
    assert registry.get("Principal Component Analysis.md").note_type == "concept"
    assert [n.path for n in registry.find_by_type("concept")] == ["Principal Component Analysis.md"]
    (vault / "Principal Component Analysis.md").unlink()
    registry.rebuild(scan_vault(vault))
    assert registry.lookup("PCA") == []


def test_lexical_lookup_ignores_tiny_shared_word(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Agent A.md").write_text("# Agent A\n", encoding="utf-8")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    assert registry.lookup("Guida a Ideaverse") == []
