import os
from pathlib import Path

import pytest

from sb_processor.registry import Registry
from sb_processor.retrieval import RetrievalPolicy, retrieve_candidate
from sb_processor.semantic import SemanticIndex
from sb_processor.vault import scan_vault


@pytest.mark.skipif(os.environ.get("SB_RUN_LOCAL_MODEL_TEST") != "1",
                    reason="Run with SB_RUN_LOCAL_MODEL_TEST=1 after caching the local ONNX model")
def test_local_model_retrieves_cross_language_dataset_note(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    vault = tmp_path / "vault"
    (vault / "Dots").mkdir(parents=True)
    (vault / "Dots" / "Dataset.md").write_text(
        "# Dataset\nA dataset is a collection of records or examples used to train and evaluate a machine learning model.")
    (vault / "Dots" / "K-Fold Cross-Validation.md").write_text(
        "# K-Fold Cross-Validation\nA resampling procedure that partitions data into k folds.")
    registry = Registry(tmp_path / "registry.sqlite")
    registry.rebuild(scan_vault(vault))
    policy = RetrievalPolicy(roots={"concept": "Dots"})
    cache = Path(__file__).resolve().parents[1] / ".data/models"
    with SemanticIndex(tmp_path / "vectors", model_cache=cache) as index:
        assert index.sync(registry, policy).indexed == 2
        for phrase in ("insieme di dati usati per addestrare un modello di apprendimento automatico",
                       "conjunto de datos utilizado para entrenar un modelo de aprendizaje automático"):
            result = retrieve_candidate(registry, phrase, [], policy, index, threshold=.50)
            assert result.candidates[0].path == "Dots/Dataset.md"
            assert "semantic" in result.candidates[0].retrieval_methods
