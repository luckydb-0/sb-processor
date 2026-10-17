# Second Brain processor PoC

## Scope and decisions

This package reads an Obsidian vault, builds a disposable SQLite index, extracts one source, asks an LLM for a validated draft, checks draft paths and existing-note matches, and stages the result. It never writes to the vault. The university workflow is the first source adapter; its rules and templates stay in the vault as external inputs.

An alternative was a two-call flow that first extracts concepts, then fetches context for a second LLM call. That could improve retrieval later, but it adds latency and another failure point. This PoC sends a compact vault inventory plus lexical context in one call, then checks every proposed note with deterministic lookup. An alternative full RAG stack is deferred until lexical retrieval proves insufficient.

## Files and responsibilities

```text
sb-processor/
  pyproject.toml                 dependencies and CLI package
  README.md                      setup and commands
  src/sb_processor/
    models.py                    validated scan, draft, proposal, review contracts
    vault.py                     read-only Markdown/frontmatter scanner
    registry.py                  rebuildable SQLite index and deterministic lookup
    pdf.py                       selectable local PDF extraction and comparison
    llm.py                       LLMClient and OpenAI Responses implementation
    pipeline.py                  generic orchestration and safety reconciliation
    staging.py                   staged JSON, Markdown, and report writer
    cli.py                       command-line entry point
    workflows/university.py      university paths and external rules/templates
    prompts/university.md        small workflow prompt, not the full rules
  tests/                         deterministic behavior and fake-LLM integration
```

## Data flow

`scan(vault)` returns note records with relative paths, metadata, bodies, mtime, and SHA-256 hashes. `Registry.rebuild` replaces the index in a transaction. Its `lookup` returns exact title, filename, alias, and lexical candidates with match kinds, without asserting equivalence. Generic `pdf.py` selects PyMuPDF text with page markers or anydoc Markdown, then applies the same nonempty and size checks. The university workflow loads the user's rules/templates and reports the vault's actual Dots/Maps/Sources roots (including an `Atlas` prefix when present). The generic pipeline selects lexical context, calls `LLMClient.generate_processing_proposal` for a Pydantic `LLMProposal`, and converts its drafts into a `ProcessingProposal` after collision and path checks. `Stager` writes only outside the vault.

## Schemas

`LLMProposal` has `source_summary`, `note_changes: list[DraftChange]`, and `review_required: list[str]`. Each `DraftChange` has `action: CREATE|UPDATE|NO_CHANGE|REVIEW_REQUIRED`, `note_type`, `title`, `target_path`, `reason`, `content` (complete Markdown), and `sources`. `ProcessingProposal` adds the source path, workflow, vault snapshot count, and reconciled `NoteChange` records. Each `NoteChange` has deterministic candidates and an optional original content hash. A later reviewer can consume this proposal and return `ReviewResult` with `PASS|FIX|REVIEW_REQUIRED`, issues, and corrections; no reviewer runs in the PoC.

## SQLite

`notes(path PRIMARY KEY, filename, filename_norm, title, title_norm, note_type, aliases_json, maps_json, frontmatter_json, body, mtime, content_hash)` plus indexed `aliases(alias_norm, path)` and indexes on normalized title, filename, and note type. The vault remains authoritative; rebuilding clears and repopulates these tables. Lexical ranking is a small deterministic token-overlap calculation, with no embeddings or FTS dependency.

## Safety and limits

- Vault paths are relative `.md` paths; absolute paths, traversal, and symlink escapes are rejected.
- Staging and database locations must be outside the vault.
- A `CREATE` colliding with an existing path or close candidate becomes `REVIEW_REQUIRED`; an `UPDATE` without its exact existing target becomes `REVIEW_REQUIRED`.
- A textless/scanned PDF fails clearly; OCR is outside this PoC.
- anydoc is an optional Python dependency and is called with `ocr="reject"` to keep conversion local. `compare-pdf` saves both raw conversions without an LLM call.
- API keys come from `OPENAI_API_KEY`; request context is saved locally for debugging and may contain source and vault text.
- A real API run needs a PDF and credentials, neither of which are present in this workspace today.
