# Second Brain processor PoC

## Scope and decisions

This package reads an Obsidian vault, builds disposable SQLite and local vector indexes, extracts one source, runs two structured Agent A passes, checks draft paths and existing-note matches, and stages the result. It never writes to the vault. The university workflow is the first source adapter; its compact instructions and templates stay in the vault as external inputs.

Pass 1 receives page-aware source evidence, completeness, compact instructions, and no existing Concept Note bodies. It returns `SourceAnalysis` with candidate concepts, maps, source-level note candidates, and observations, without vault actions. A deterministic supplement adds short explicit “What is a/an X?” definition headings missed by the model. A configurable cap keeps the highest-importance concepts for Pass 2 and reports omissions. `knowledge/retrieval.py` searches each candidate independently against policy-filtered SQLite metadata and local semantic results. Pass 2 receives selected full note bodies and resolves conceptual relationships before returning a validated `ProcessingProposal`. The vector index is a disposable derivative of global `Dots/` knowledge notes. Agent B independently reviews the staged proposal.

## Files and responsibilities

```text
sb-processor/
  pyproject.toml                 dependencies and CLI package
  README.md                      setup and commands
  src/sb_processor/
    models.py                    shared validated scan, proposal, and review contracts
    cli.py                       command-line composition root
    documents/
      extraction.py              page-aware extractor adapters and provenance models
      cleaning.py                deterministic, auditable document cleanup
      visual.py                  selective page renderer, visual adapter, cache
      ingestion.py               generic PDF ingestion and inspection artifacts
      comparison.py              raw/clean benchmark artifacts and metrics
      pdf.py                     compatibility wrapper for local PDF options
    knowledge/
      vault.py                   read-only Markdown/frontmatter scanner
      registry.py                rebuildable SQLite index and deterministic lookup
      retrieval.py               path/type policy and metadata-first ranking
      semantic.py                FastEmbed ONNX and persistent local Qdrant index
    processing/
      agent_a.py                 typed request assembly and context diagnostics
      llm.py                     LLMClient and OpenAI Responses implementation
      pipeline.py                generic orchestration and safety reconciliation
      staging.py                 staged JSON, Markdown, and report writer
    review/
      runner.py                  independent structured review runner and staging
      context.py                 selective per-change source and retrieval evidence
      evidence.py                evidence binding and correction constraints
      validators.py              deterministic note and wikilink checks
      batch.py                   aggregate review request and issue grouping
      checks.py                  mandatory review-check definitions
    workflows/university.py      university paths and external instructions/templates
    workflows/university_review.py university review rules and PDF page images
    prompts/university.md        small workflow prompt
    prompts/visual_page.md       visual-only extraction instructions
  tests/
    documents/                   extraction, cleanup, ingestion, and visual tests
    knowledge/                   vault, registry, retrieval, and semantic tests
    processing/                  Agent A, proposal, pipeline, and staging tests
    review/                      Agent B context, evidence, validator, and runner tests
    workflows/                   source-specific adapter tests
    test_cli.py                  cross-feature command-line tests
```

## Data flow

`scan(vault)` returns note records with relative paths, metadata, bodies, mtime, and SHA-256 hashes. `Registry.rebuild` replaces the index in a transaction. Its `lookup` returns exact title, filename, alias, and lexical candidates without asserting equivalence. The existing ingestion modules retain raw page/block text, auditable cleanup, visual flags, and machine-readable completeness. The university workflow sends cleaned page text and page-aligned visual descriptions, normally with only compact instructions and templates. The generic pipeline blocks partial sources unless explicitly overridden, builds `AgentADiscoveryRequest`, calls `LLMClient.analyze_source`, performs per-candidate deterministic and semantic retrieval, then builds `AgentARequest` for `LLMClient.generate_processing_proposal`. Application code reconciles the draft after collision, scope, and path checks. Staging records both pass diagnostics, retrieval evidence, index sync statistics, and proposed wikilinks. Agent B reads that staging and the external review Markdown, checks the vault snapshot, and reviews each change with selected source pages, retrieval evidence, and original rendered pages when visual evidence was selected. Results and corrections remain separate under `agent_b/`.

## Schemas

`ExtractedPage` keeps raw and cleaned text, visual flags, visual content, status, and original page number. `ExtractedDocument.completeness` derives `COMPLETE` or `PARTIAL` with processed and unresolved visual page lists. `SourceAnalysis` has candidate concepts (names, observed terms, source pages, importance), maps, source-level note candidates, and observations. Pass 1 cannot issue vault actions. `LLMProposal` has `source_summary`, `note_changes: list[DraftChange]`, `concept_resolutions`, and `review_required`. Concept relations include new, equivalent, broader, narrower, related but distinct, and ambiguous. Each `DraftChange` has `action: CREATE|UPDATE|NO_CHANGE|REVIEW_REQUIRED`, `note_type`, `title`, `target_path`, `reason`, `content` (complete Markdown), and `sources`. `ProcessingProposal` adds the source path, workflow, vault snapshot count, source completeness, concept resolutions, and reconciled `NoteChange` records. `AgentBRequest` and Structured Outputs `ChangeReview` add per-change evidence, alias relations, and Dot-promotion assessment. The aggregate `ReviewResult` has one status per change and typed issues with proposed corrections and source pages.

## SQLite

`notes(path PRIMARY KEY, filename, filename_norm, title, title_norm, note_type, aliases_json, maps_json, frontmatter_json, body, mtime, content_hash)` plus indexed `aliases(alias_norm, path)` and indexes on normalized title, filename, and note type. The vault remains authoritative; rebuilding clears and repopulates these tables. Metadata queries omit `body`; selected bodies are fetched by path. Lexical ranking is deterministic token overlap; there is no FTS extension dependency.

## Semantic index

`SemanticIndex` uses Qdrant local mode and FastEmbed's local ONNX model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Only notes admitted as `concept` by the retrieval policy are indexed. A point stores vault-relative path, title, aliases, note type, and source content hash. Vector input is title, aliases, and the first 1,800 body characters. The collection name includes model identity and representation version. Sync reuses equal hashes, embeds new/changed notes, and deletes absent notes. The index can be deleted and rebuilt from the vault. Query scores are candidate-generation evidence, never merge decisions. The initial cutoff is `0.50`, set from a small fixture distribution and configurable on the CLI; exact/alias hits survive cutoff and per-candidate top-k trimming. Raw semantic observations are staged, while only selected candidate metadata enters Pass 2.

## Safety and limits

- Vault paths are relative `.md` paths; absolute paths, traversal, and symlink escapes are rejected.
- Staging and database locations must be outside the vault.
- The vector index and model cache must be outside the vault.
- A `CREATE` colliding with an existing path or exact title, filename, alias, or canonical Map-name candidate becomes `REVIEW_REQUIRED`; loose lexical overlap remains visible. An `UPDATE` without its exact existing target and supplied full body becomes `REVIEW_REQUIRED`.
- A textless/scanned PDF fails clearly; OCR is outside this PoC.
- AnyDoc and PyMuPDF4LLM are optional Python dependencies. AnyDoc is called with `ocr="reject"` to keep conversion local. `compare-pdf` saves raw and cleaned artifacts for all three adapters without an LLM call.
- Unresolved visual pages gate the proposal call. `--allow-incomplete-visuals` records `PARTIAL`, marks proposed writes `REVIEW_REQUIRED`, and adds a review item.
- Only successful, unambiguous visual results enter the cache. API failures leave page status `FAILED` and the document partial.
- API keys come from `OPENAI_API_KEY`; request context is saved locally for debugging and may contain source and vault text.
- A real API run requires credentials and must be reviewed before any staged proposal is manually applied.
- A discovery cap reports omitted concept candidates. A broad alias mapping to a narrower existing title is held for scope review. Proposed wikilinks are classified as existing, created in the proposal, or unresolved; unresolved links do not block staging yet.
