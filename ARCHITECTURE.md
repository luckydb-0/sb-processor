# Second Brain processor PoC

## Scope and decisions

This package reads an Obsidian vault, builds a disposable SQLite index, extracts one source, asks an LLM for a validated draft, checks draft paths and existing-note matches, and stages the result. It never writes to the vault. The university workflow is the first source adapter; its compact instructions and templates stay in the vault as external inputs.

This PoC uses one Agent A call. Before it, `retrieval.py` filters SQLite note metadata using a workflow policy, ranks title/filename/alias/lexical candidates, and loads only bounded relevant full bodies. The typed request contains workflow instructions, templates, page-aware source evidence, completeness, candidate metadata, and selected existing bodies. Embeddings and a second retrieval call are deferred.

## Files and responsibilities

```text
sb-processor/
  pyproject.toml                 dependencies and CLI package
  README.md                      setup and commands
  src/sb_processor/
    models.py                    validated scan, draft, proposal, review contracts
    vault.py                     read-only Markdown/frontmatter scanner
    registry.py                  rebuildable SQLite index and deterministic lookup
    retrieval.py                 path/type policy and metadata-first ranking
    agent_a.py                   typed request assembly and context diagnostics
    pdf.py                       compatibility wrapper for local PDF options
    extraction.py                page-aware extractor adapters and provenance models
    cleaning.py                  deterministic, auditable document cleanup
    visual.py                    selective page renderer, visual adapter, cache
    ingestion.py                 generic PDF ingestion and inspection artifacts
    comparison.py                raw/clean benchmark artifacts and metrics
    llm.py                       LLMClient and OpenAI Responses implementation
    pipeline.py                  generic orchestration and safety reconciliation
    staging.py                   staged JSON, Markdown, and report writer
    cli.py                       command-line entry point
    workflows/university.py      university paths and external instructions/templates
    prompts/university.md        small workflow prompt
    prompts/visual_page.md       visual-only extraction instructions
  tests/                         deterministic behavior and fake-LLM integration
```

## Data flow

`scan(vault)` returns note records with relative paths, metadata, bodies, mtime, and SHA-256 hashes. `Registry.rebuild` replaces the index in a transaction. Its `lookup` returns exact title, filename, alias, and lexical candidates with match kinds, without asserting equivalence. `extraction.py` selects page-aware PyMuPDF, AnyDoc, or PyMuPDF4LLM adapters. `cleaning.py` retains raw page/block text and records auditable cleanup and visual flags. `ingestion.py` enriches only flagged pages and derives machine-readable completeness. The university workflow sends cleaned text and page-aligned visual descriptions, normally with only compact instructions and templates. The generic pipeline blocks partial sources unless explicitly overridden, retrieves note metadata under the workflow policy, builds `AgentARequest`, calls `LLMClient.generate_processing_proposal`, and converts its Pydantic draft into `ProcessingProposal` after collision and path checks. Staging writes only outside the vault and records context diagnostics.

## Schemas

`ExtractedPage` keeps raw and cleaned text, visual flags, visual content, status, and original page number. `ExtractedDocument.completeness` derives `COMPLETE` or `PARTIAL` with processed and unresolved visual page lists. `LLMProposal` has `source_summary`, `note_changes: list[DraftChange]`, and `review_required: list[str]`. Each `DraftChange` has `action: CREATE|UPDATE|NO_CHANGE|REVIEW_REQUIRED`, `note_type`, `title`, `target_path`, `reason`, `content` (complete Markdown), and `sources`. `ProcessingProposal` adds the source path, workflow, vault snapshot count, source completeness, and reconciled `NoteChange` records. Each `NoteChange` has deterministic candidates and an optional original content hash. A later reviewer can consume this proposal and return `ReviewResult` with `PASS|FIX|REVIEW_REQUIRED`, issues, and corrections; no reviewer runs in the PoC.

## SQLite

`notes(path PRIMARY KEY, filename, filename_norm, title, title_norm, note_type, aliases_json, maps_json, frontmatter_json, body, mtime, content_hash)` plus indexed `aliases(alias_norm, path)` and indexes on normalized title, filename, and note type. The vault remains authoritative; rebuilding clears and repopulates these tables. Metadata queries omit `body`; selected bodies are fetched by path. Lexical ranking is deterministic token overlap, with no embeddings or FTS dependency.

## Safety and limits

- Vault paths are relative `.md` paths; absolute paths, traversal, and symlink escapes are rejected.
- Staging and database locations must be outside the vault.
- A `CREATE` colliding with an existing path or exact title, filename, or alias candidate becomes `REVIEW_REQUIRED`; loose lexical overlap remains visible. An `UPDATE` without its exact existing target and supplied full body becomes `REVIEW_REQUIRED`.
- A textless/scanned PDF fails clearly; OCR is outside this PoC.
- AnyDoc and PyMuPDF4LLM are optional Python dependencies. AnyDoc is called with `ocr="reject"` to keep conversion local. `compare-pdf` saves raw and cleaned artifacts for all three adapters without an LLM call.
- Unresolved visual pages gate the proposal call. `--allow-incomplete-visuals` records `PARTIAL`, marks proposed writes `REVIEW_REQUIRED`, and adds a review item.
- Only successful, unambiguous visual results enter the cache. API failures leave page status `FAILED` and the document partial.
- API keys come from `OPENAI_API_KEY`; request context is saved locally for debugging and may contain source and vault text.
- A real API run requires credentials and must be reviewed before any staged proposal is manually applied.
