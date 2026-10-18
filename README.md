# Second Brain processor PoC

A command-line proof of concept for processing sources against an Obsidian vault. It indexes Markdown notes in disposable SQLite and local Qdrant indexes, extracts and cleans a source PDF, runs two structured Agent A passes, checks target paths and possible matches, and saves drafts for review. It **never writes to the vault**.

The only processing workflow currently implemented is `university`, for one lecture PDF at a time. Normal runs use the compact University Processing Instructions and templates from the vault. The long University Material Processing Rules remain reference material and enter a request only when explicitly selected with `--rules`.

## Setup

From `sb-processor/`, with Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,semantic]'
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

`scan` builds `.data/registry.sqlite`; `lookup` searches that database. `process` rebuilds SQLite, incrementally syncs the local vector index, and writes a proposal to `staging/run_<UTC timestamp>_<id>/`, never to the vault. Keep `--database`, `--semantic-index`, `--embedding-cache`, and `--staging` outside the vault. Review `review.md`, `proposal.json`, and the Markdown under `notes/` before manually using any draft.

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

Agent A Pass 1 receives page-aware source evidence, completeness, compact workflow instructions, and no existing Concept Note bodies. Its Pydantic `SourceAnalysis` names candidate concepts, maps, and source-level notes without deciding vault actions. A small deterministic supplement preserves short explicit “What is a/an X?” definition headings that a broad lecture analysis may omit; the added names are audited. Discovery is capped at 20 important concepts by default (`--max-discovered-concepts`); any omitted candidates are recorded for review. Pass 2 retrieves evidence independently for each selected concept: exact title, filename, alias, spacing/hyphenation variant, lexical, and local semantic similarity. Exact and alias candidates outrank semantic hits; semantic scores never trigger a merge. A workflow policy limits concept equivalence searches and semantic indexing to `Dots/` regardless of source origin. README, prompts, configuration, staging, and instruction files are excluded. Full bodies are loaded only for the bounded selected candidates and source/map context. Missing candidates do not prove novelty.

The default local embedding model is [`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), run through FastEmbed ONNX on the local machine. [FastEmbed lists it](https://qdrant.github.io/fastembed/examples/Supported_Models/) as a 384-dimensional multilingual model of about 220 MB. It was selected for English, Italian, and Spanish similarity with a modest PoC footprint. The model is downloaded to `.data/models` on first use; embeddings are never sent to an external API. `--embedding-model`, `--embedding-cache`, and `--semantic-index` are configurable. The representation is deterministic: title, aliases, then the first 1,800 body characters. A model or representation-version change creates a separate Qdrant collection. Sync compares vault content hashes, reuses unchanged vectors, updates changed notes, and deletes removed notes; deleting the disposable index allows a full rebuild from the vault.

The initial semantic cutoff is `0.50` (`--semantic-threshold`), with at most four candidates per concept (`--candidate-top-k`). This cutoff was checked against the small Machine Learning fixture: exact topic queries scored roughly 0.66–0.78, unrelated notes mostly below 0.48, and an Italian Dataset paraphrase about 0.54. It is a conservative candidate-generation setting from a small sample, not an equivalence probability. Raw scores above and below the cutoff are saved in the retrieval audit but omitted from Pass 2 to keep its context smaller.

Each run contains:

```text
source_analysis.json       full Pass 1 structured discovery
discovery_selection.json  selected and omitted concept candidates
pass1_request.json         exact Pass 1 context
pass1_diagnostics.json     Pass 1 size breakdown
request_context.json       exact Pass 2 context
context_diagnostics.json   Pass 2 size breakdown and exclusions
retrieval_evidence.json    candidate-by-candidate methods and all semantic scores
semantic_diagnostics.json  model, index sync, and query counts
proposal.json             validated proposal and concept resolutions
wikilinks.json            existing, same-proposal, and unresolved links
review.md                 readable decisions and audit
notes/                    proposed complete Markdown files
conflicts/                duplicate-target drafts when present
```

`request_context.json` contains page-aware extracted source text, selected candidate evidence, and selected vault note content. The diagnostics record instruction, template, source, existing-body, candidate-metadata, and total request sizes; selected bodies; and excluded paths. Token count is a characters/4 estimate. Keep staging local and private. Review all proposed Markdown and original note hashes before any later manual copy or future approval workflow.

## What the code checks

The registry supports normalized exact title, filename, alias, path, and note-type queries, plus lexical candidate search. Retrieval returns possible notes, never a semantic-equivalence decision. A `CREATE` with an exact/alias/normalized-variant collision or an existing target becomes `REVIEW_REQUIRED`; loose lexical and semantic overlap stays visible without automatically blocking creation. An `UPDATE` becomes `REVIEW_REQUIRED` if its target does not exist or its full current body was not sent to the model. An ambiguous concept resolution, conflicting existing path, or broad alias pointing to a narrower existing title also requires review. Unsafe paths, paths outside workflow roots, duplicate targets, and missing Markdown content require review. With an explicit incomplete-visual override, proposed writes become `REVIEW_REQUIRED`. Unresolved wikilinks are reported, not blocked. All proposals remain staged only.

All three text extractors run locally and accept text-based PDFs. The `anydoc` path explicitly uses `ocr="reject"`; it never invokes anydoc's hosted OCR, which would send a PDF to Firecrawl. Image-only PDFs need OCR before this PoC can process them. Visual enrichment sends only detector-flagged page images to the configured OpenAI API. Sources over 120,000 cleaned source characters are rejected instead of silently truncated. There is no web app, Agent B execution, or vault write operation.

## Tests

```bash
python -m pytest -q
```

Tests cover scanning/frontmatter, policy-aware metadata retrieval, alias and filename ranking, context size bounds, safe staging, update checks, PDF extractors, comparison output, completeness gating, selective rendering, caching, failures, and both OpenAI request shapes. They use fake clients for deterministic integration; a live Agent A run requires a PDF and `OPENAI_API_KEY`.

After the local model has been cached, run the actual multilingual retrieval test without cloud access with `SB_RUN_LOCAL_MODEL_TEST=1 python -m pytest -q`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the file map, schemas, SQLite tables, and design choices. The [ingestion v1 technical debt list](docs/technical-debt/ingestion-v1.md) records known follow-up work for Agent A and PDF ingestion.
