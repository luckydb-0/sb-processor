# Conceptual Package Layout Design

## Intent

Reorganize the PoC so files that change for the same reason live together. The refactor should make the source and test trees easier to navigate without changing processing behavior, the installed `sb-processor` command, staged artifact formats, or vault-safety guarantees.

## Goals

- Group document ingestion, vault knowledge access, proposal processing, and independent review into explicit Python subpackages.
- Mirror those conceptual groups in the test tree.
- Update internal imports, monkeypatch targets, package data configuration, and architectural documentation.
- Preserve all current behavior, verified by the existing test suite.

## Non-goals and anti-goals

- Do not redesign algorithms, schemas, CLI arguments, prompts, or output formats.
- Do not split `models.py` into domain-specific model files during this refactor; it is a shared contract layer and splitting it would introduce avoidable dependency risk.
- Do not keep deprecated flat-module wrappers. The package is still at version `0.1.0`, its documented interface is the CLI, and wrappers would preserve the clutter this change is intended to remove.
- Do not move source-specific behavior out of the existing `workflows/` package.

## Selected structure

```text
src/sb_processor/
  __init__.py
  __main__.py
  cli.py
  models.py
  documents/
    __init__.py
    extraction.py
    cleaning.py
    visual.py
    ingestion.py
    comparison.py
    pdf.py
  knowledge/
    __init__.py
    vault.py
    registry.py
    retrieval.py
    semantic.py
  processing/
    __init__.py
    agent_a.py
    llm.py
    pipeline.py
    staging.py
  review/
    __init__.py
    runner.py
    context.py
    evidence.py
    validators.py
    batch.py
    checks.py
  workflows/
    __init__.py
    university.py
    university_review.py
```

Tests will mirror the same concepts:

```text
tests/
  test_cli.py
  documents/
  knowledge/
  processing/
  review/
  workflows/
```

`test_agent_b_cli.py` belongs under `tests/review/` because it protects the review command surface. `test_optional_semantic_import.py` belongs under `tests/knowledge/` because it protects the optional semantic-index dependency boundary. The remaining tests map directly to the source concern they exercise.

## Dependency direction

- `models.py` remains the shared contract layer.
- `documents/` owns source extraction and enrichment and depends only on shared contracts where necessary.
- `knowledge/` owns vault metadata and retrieval; it may depend on shared contracts.
- `processing/` orchestrates `documents/` and `knowledge/` to produce proposals.
- `review/` consumes proposals and knowledge metadata to produce independent reviews.
- `workflows/` adapts source-specific rules using the lower-level packages.
- `cli.py` is the composition root and may import every feature package.

The move will use package-relative imports inside `sb_processor` and fully qualified imports in tests. Import cycles will not be solved with delayed imports or compatibility shims; the current dependency direction must remain explicit.

## Approaches considered

1. **Balanced conceptual packages — selected.** Clear ownership and mirrored tests with moderate import churn and no behavioral redesign.
2. **Minimal grouping.** Move only document and review modules. This reduces churn but leaves the root structurally inconsistent and does not fully address the request.
3. **Full domain decomposition.** Split shared models as well as implementation modules. This offers stricter ownership but creates unnecessary schema and circular-dependency risk for the PoC.

## Verification

- Run the full existing test suite after moves and import updates; the baseline is 151 passed and 1 skipped.
- Run an import/CLI smoke check for `python -m sb_processor --help`.
- Inspect the final source and test trees for stray flat feature modules.
- Update `ARCHITECTURE.md` so its file map and dependency description match the code.
