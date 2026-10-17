# Second Brain processor PoC

A command-line proof of concept for processing sources against an Obsidian vault. It indexes Markdown notes in a disposable SQLite database, extracts and cleans a source PDF, asks an OpenAI model for a Pydantic-validated note proposal, checks target paths and possible matches, and saves drafts for review. It **never writes to the vault**.

The only processing workflow currently implemented is `university`, for one lecture PDF at a time. Normal runs use the compact University Processing Instructions and templates from the vault. The long University Material Processing Rules remain reference material and enter a request only when explicitly selected with `--rules`.

## Setup

From `sb-processor/`, with Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

The default PDF extractor is PyMuPDF. To select the optional extractors, install their extras:

```bash
python -m pip install -e '.[anydoc,layout]'
```

`compare-pdf` always runs all three extractors, so it needs **both** extras. Scanning, lookup, local PDF comparison, and `ingest-pdf --skip-visual` do not need an API key. For visual enrichment or `process`, set `OPENAI_API_KEY` in the shell before running the command:

```bash
export OPENAI_API_KEY='your-key'
```

The application reads this variable through the OpenAI SDK; it does not load `.env` files automatically. `.env`, `.data/`, `staging/`, and `output/` are Git-ignored, but staged files can contain source and vault text, so keep them private.

## Quick start

Run from `sb-processor/`. The examples use the sibling `gd-gdb` directory as the vault. The default database, cache, and staging paths then stay outside it.

```bash
python -m sb_processor scan --vault ../gd-gdb
python -m sb_processor lookup 'Guida a Ideaverse'
python -m sb_processor ingest-pdf --source /path/to/lecture.pdf --vault ../gd-gdb --skip-visual
python -m sb_processor process --workflow university --source /path/to/lecture.pdf --vault ../gd-gdb
```

`scan` builds `.data/registry.sqlite`; `lookup` searches that database. `process` rebuilds it automatically, so a separate scan is optional before processing. It writes a proposal to `staging/run_<UTC timestamp>_<id>/`, never to the vault. Use `--database` and `--staging` to change those paths, keeping both outside the vault. Review `review.md`, `proposal.json`, and the Markdown under `notes/` before manually using any draft.

The university workflow expects `University Templates.md` and `Agent A - University Compact Processing Instructions.md` under the vault's `+ Inbox` folder. Use `--templates` and `--instructions` if they live elsewhere. `--rules` explicitly replaces the compact instructions with a long rules file; it cannot be combined with `--instructions`. `--model` selects a Structured Outputs capable OpenAI model (default `gpt-4o-mini`).

## PDF ingestion and extractor comparison

Inspect extraction and visual-page detection without generating a note proposal:

```bash
python -m sb_processor ingest-pdf --source /path/to/lecture.pdf --vault ../gd-gdb
python -m sb_processor compare-pdf --source /path/to/lecture.pdf --vault ../gd-gdb
```

`ingest-pdf` uses the visual model only for flagged pages. With no API key or with `--skip-visual`, those pages stay unresolved. `compare-pdf` uses no model or API key; it compares PyMuPDF, AnyDoc, and PyMuPDF4LLM locally. Use `--pdf-extractor anydoc` or `--pdf-extractor pymupdf4llm` with `ingest-pdf` or `process` after installing the corresponding extra.

The extractor returns numbered pages with raw text, positioned blocks where available, and image/drawing coverage metadata. The deterministic cleaner removes repeated edge-position headers/footers and page counters, suppresses later near-duplicate navigation pages, consolidates contiguous running section labels, normalizes known ligatures and whitespace artefacts, and joins clear wraps within text blocks. Each transformation has an auditable action in the structured document. Original PDF text and page numbers remain intact. AnyDoc single-page failures fall back to raw PyMuPDF for that page and are recorded in metadata.

Pages with little extracted text and substantial image or vector coverage receive `requires_visual_processing` and `visual_flags`. `ingest-pdf` renders only those pages and asks an OpenAI vision model to extract additional visible relationships. It stores raw text, cleaned text, and visual descriptions separately under `staging/ingestion/ingest_<id>/` as `document.json`, `text_raw.md`, `text_clean.md`, `agent_context.md`, and `summary.json`. The default visual model is `gpt-5.4`, chosen after the benchmark's nested-oval diagram was misread by smaller models; set `--visual-model` to change it. The model receives one page rendered at 2× and local context. Successful results are cached in `.data/visual_cache` using the source hash, rendered page hash, and model/prompt identity. Output and cache locations must be outside the vault.

The document's `completeness` object reports `COMPLETE` or `PARTIAL`, flagged pages, processed pages, and unresolved pages. A failed, empty, or ambiguous visual response remains unresolved. If the API key is unavailable or `--skip-visual` is set, flagged pages remain `PENDING`. `process` stops before the proposal call on a partial source. To proceed deliberately, pass `--allow-incomplete-visuals`; the staged proposal retains `PARTIAL` and lists unresolved pages for review. The source context preserves original page numbers and labels text and visual content separately. No specialized table fallback runs.

`compare-pdf` runs all three backends locally without a model or API key. Each run saves `<extractor>_raw.md`, `<extractor>_clean.md`, `<extractor>_document.json`, `comparison.json`, `comparison.md`, and `cleaning_report.md`. The JSON retains raw page text, block and line positions, section ranges, visual features, and cleaning decisions; `anydoc_whole_document.md` preserves the prior whole-document conversion separately because it cannot reliably identify source pages. Character/word savings are measured, while token counts use a rough characters/4 estimate. Inspect representative slides: headings, reading order, tables, diagrams, equations, and bibliography can differ even when word counts look similar. `--vault` is required so output cannot be placed inside the vault.

The university adapter reports vault-relative note roots to the model. In this vault, the suggested roots are `Atlas/Dots`, `Atlas/Maps`, and `Atlas/Sources/University`; in a vault without an `Atlas/Dots` folder they are `Dots`, `Maps`, and `Sources/University`.

Agent A retrieval first queries SQLite for path, title, filename, type, aliases, and maps without reading note bodies. A workflow policy admits relevant Dots, Maps, and university source notes, then ranks exact, filename, alias, and lexical matches. README, prompts, configuration, staging, and instruction files are excluded as knowledge candidates. Only a capped set of ranked full bodies enters the typed Agent A request. If a body exceeds the size budget, it remains metadata-only and any attempted UPDATE requires review. Retrieval is deterministic: no match does not establish that a concept is new.

Each run contains:

```text
proposal.json         validated proposal with actions, matches, and source hashes
request_context.json  exact non-secret context sent to the model
context_diagnostics.json  character/token estimates, selected notes, and exclusions
review.md             readable actions, reasons, candidate matches, staged paths
notes/                proposed complete Markdown files at their target paths
conflicts/            duplicate-target drafts when present
```

`request_context.json` contains page-aware extracted source text and selected vault note content. `context_diagnostics.json` records instruction, template, source, existing-body, candidate-metadata, and total request sizes; which candidate bodies were loaded; and excluded paths. Token count is a characters/4 estimate. Keep staging local and private. Review all proposed Markdown and the original note hashes before any later manual copy or future approval workflow.

## What the code checks

The registry supports normalized exact title, filename, alias, path, and note-type queries, plus a simple lexical candidate search. Lookup returns possible notes, never a semantic-equivalence decision. A `CREATE` with an exact title, filename, or alias collision or an existing target becomes `REVIEW_REQUIRED`; loose lexical overlap stays visible without automatically blocking creation. An `UPDATE` becomes `REVIEW_REQUIRED` if its target does not exist or its full current body was not sent to the model. Unsafe paths, paths outside workflow roots, duplicate targets, and missing Markdown content also require review. With an explicit incomplete-visual override, proposed writes become `REVIEW_REQUIRED`. The model is asked to make explicit `NO_CHANGE` decisions for supplied existing bodies; omissions become review items. All proposals remain staged only.

All three text extractors run locally and accept text-based PDFs. The `anydoc` path explicitly uses `ocr="reject"`; it never invokes anydoc's hosted OCR, which would send a PDF to Firecrawl. Image-only PDFs need OCR before this PoC can process them. Visual enrichment sends only detector-flagged page images to the configured OpenAI API. Sources over 120,000 Agent A context characters are rejected instead of silently truncated. No embeddings, vector database, web app, Agent B execution, or vault write operation is included.

## Tests

```bash
python -m pytest -q
```

Tests cover scanning/frontmatter, policy-aware metadata retrieval, alias and filename ranking, context size bounds, safe staging, update checks, PDF extractors, comparison output, completeness gating, selective rendering, caching, failures, and both OpenAI request shapes. They use fake clients for deterministic integration; a live Agent A run requires a PDF and `OPENAI_API_KEY`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the file map, schemas, SQLite tables, and design choices. The [ingestion v1 technical debt list](docs/technical-debt/ingestion-v1.md) records known follow-up work for Agent A and PDF ingestion.
