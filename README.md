# Second Brain processor PoC

A small, source-agnostic processing pipeline for an Obsidian vault. It scans Markdown, builds a disposable SQLite registry, asks an LLM for a Pydantic-validated proposal, checks proposed note paths and deterministic matches, and writes inspection files to staging. It does **not** write to the vault.

The first workflow reads one university lecture PDF. It loads the existing University Material Processing Rules, templates, and Agent A instructions from the vault at runtime. Those files remain the source of truth for university note content. The package's own university prompt is only a short bridge to the structured schema.

## Setup

From this directory, with Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,anydoc]'
export OPENAI_API_KEY='your-key'
```

Keep the key in the environment or a local, uncommitted `.env` file. The application reads `OPENAI_API_KEY` through the OpenAI SDK; it does not load or save keys itself. `.env`, `.data/`, and `staging/` are ignored if this directory is placed under Git.

## Commands

Run from this directory so the default database and staging paths stay outside the vault:

```bash
python -m sb_processor scan --vault ../gd-gdb
python -m sb_processor lookup 'Guida a Ideaverse'
python -m sb_processor process --workflow university --source /path/to/lecture.pdf --vault ../gd-gdb
python -m sb_processor process --workflow university --source /path/to/lecture.pdf --vault ../gd-gdb --pdf-extractor anydoc
python -m sb_processor process --workflow university --source /path/to/lecture.pdf --vault ../gd-gdb --pdf-extractor pymupdf4llm
python -m sb_processor compare-pdf --source /path/to/lecture.pdf --output-dir output/extraction_comparison --vault ../gd-gdb
```

The process command rebuilds the registry automatically. Its default output paths are `.data/registry.sqlite` and `staging/run_<UTC timestamp>_<id>/`. Override with `--database` and `--staging`; both must resolve outside the vault. Use `--model` to select a Structured Outputs capable OpenAI model (default `gpt-4o-mini`). Use `--rules`, `--templates`, and `--instructions` to supply alternate university files. Without overrides, the workflow expects the three files in the vault's `+ Inbox` folder.

`--pdf-extractor` selects `pymupdf` (default), `anydoc`, or `pymupdf4llm`. Install optional backends with `pip install -e '.[anydoc,layout]'`. The extractor returns numbered pages with raw text, positioned blocks where available, and image/drawing coverage metadata. The deterministic cleaner removes repeated edge-position headers/footers and page counters, suppresses later near-duplicate navigation pages, consolidates contiguous running section labels, normalizes known ligatures and whitespace artefacts, and joins clear wraps within text blocks. Each transformation has an auditable action in the structured document. Original PDF text and page numbers remain intact. AnyDoc single-page failures fall back to raw PyMuPDF for that page and are recorded in metadata.

Pages with little extracted text and substantial image or vector coverage receive `requires_visual_processing` and `visual_flags` in the structured output. This is a review signal: no visual model or specialized table fallback runs. The existing workflow sends cleaned page-marked text to the model; it does not yet use the visual flags to gate proposals.

`compare-pdf` runs all three backends locally without a model or API key. Each run saves `<extractor>_raw.md`, `<extractor>_clean.md`, `<extractor>_document.json`, `comparison.json`, `comparison.md`, and `cleaning_report.md`. The JSON retains raw page text, block and line positions, section ranges, visual features, and cleaning decisions; `anydoc_whole_document.md` preserves the prior whole-document conversion separately because it cannot reliably identify source pages. Character/word savings are measured, while token counts use a rough characters/4 estimate. Inspect representative slides: headings, reading order, tables, diagrams, equations, and bibliography can differ even when word counts look similar. `--vault` is required so output cannot be placed inside the vault.

The university adapter reports vault-relative note roots to the model. In this vault, the suggested roots are `Atlas/Dots`, `Atlas/Maps`, and `Atlas/Sources/University`; in a vault without an `Atlas/Dots` folder they are `Dots`, `Maps`, and `Sources/University`.

Each run contains:

```text
proposal.json         validated proposal with actions, matches, and source hashes
request_context.json  exact non-secret context sent to the model
review.md             readable actions, reasons, candidate matches, staged paths
notes/                proposed complete Markdown files at their target paths
conflicts/            duplicate-target drafts when present
```

`request_context.json` contains extracted source text and selected vault note content. Keep staging local and private. Review all proposed Markdown and the original note hashes before any later manual copy or future approval workflow.

## What the code checks

The registry supports normalized exact title, filename, alias, path, and note-type queries, plus a simple lexical candidate search. Lookup returns possible notes, never a semantic-equivalence decision. A `CREATE` with candidates or an existing target becomes `REVIEW_REQUIRED`. An `UPDATE` becomes `REVIEW_REQUIRED` if its target does not exist or its current body was not sent to the model. Unsafe paths, duplicate targets, and missing Markdown content also require review. All proposals remain staged only, including those marked `CREATE` or `UPDATE`.

All three extractors run locally and accept text-based PDFs. The `anydoc` path explicitly uses `ocr="reject"`; it never invokes anydoc's hosted OCR, which would send a PDF to Firecrawl. Image-only PDFs need OCR before this PoC can process them. Sources over 120,000 cleaned characters are rejected instead of silently truncated. No embeddings, vector database, web app, Agent B execution, or vault write operation is included.

## Tests

```bash
python -m pytest -q
```

Tests cover scanning/frontmatter, registry rebuild and matching, safe staging, update checks, both PDF extractors, comparison output, and the OpenAI structured-output call shape. They use a fake LLM for deterministic integration; a live OpenAI processing run requires a PDF and `OPENAI_API_KEY`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the file map, schemas, SQLite tables, and design choices.
