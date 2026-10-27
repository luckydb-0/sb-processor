# Second Brain processor PoC

A command-line proof of concept for processing sources against an Obsidian vault. It indexes Markdown notes in disposable SQLite and local Qdrant indexes, extracts and cleans a source PDF, runs two structured Agent A passes, and can run an independent Agent B review. It **never writes to the vault**.

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
# Optional, substantially larger local layout/table model stack:
python -m pip install -e '.[docling]'
```

`compare-pdf` runs the original three extractors by default, so it needs **both** `anydoc` and `layout` extras. Add `--include-docling` after installing its extra. Docling may download local model weights on first use. Scanning, lookup, local PDF comparison, and `ingest-pdf --skip-visual` do not need an API key. For visual enrichment or `process`, set `OPENAI_API_KEY` in the shell before running the command:

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
python -m sb_processor process --workflow university --source /path/to/lecture.pdf --vault ../gd-gdb --with-agent-b
python -m sb_processor review --run staging/run_<id> --vault ../gd-gdb
python -m sb_processor reconcile --run staging/run_<id> --vault ../gd-gdb
```

`scan` builds `.data/registry.sqlite`; `lookup` searches that database. `process` rebuilds SQLite, incrementally syncs the local vector index, and writes a proposal to `staging/run_<UTC timestamp>_<id>/`, never to the vault. Keep `--database`, `--semantic-index`, `--embedding-cache`, and `--staging` outside the vault. Review `review.md`, `proposal.json`, and the Markdown under `notes/` before manually using any draft.

The university workflow expects `University Templates.md` and `Agent A - University Compact Processing Instructions.md` under the vault's `+ Inbox` folder. Use `--templates` and `--instructions` if they live elsewhere. `--rules` explicitly replaces the compact instructions with a long rules file; it cannot be combined with `--instructions`. `--model` selects a Structured Outputs capable OpenAI model (default `gpt-4o-mini`).

Agent B uses the existing `+ Inbox/Agent B - University Processing Review Instructions.md` in the selected vault. Use `review --instructions` or `process --agent-b-instructions` when the rules file is elsewhere. The `review` command operates on an existing staged Agent A run; `--with-agent-b` runs it immediately after Agent A. Agent B checks that the selected vault has the proposal's note count and original hashes for updated notes.

Agent B saves `agent_b/review.json`, `agent_b/report.md`, `agent_b/requests/`, and `agent_b/diagnostics.json` beside the original `proposal.json` and `notes/`. Objective corrected Markdown, when supplied, goes under `agent_b/corrected_notes/`. The original proposal is preserved. Every proposed change receives `PASS`, `FIX`, or `REVIEW_REQUIRED`; the overall status is the highest intervention needed. The reviewer assesses aliases individually and Dot promotion for new Concept Notes. It receives selected source pages from Agent A's provenance and explicit note citations, related existing-note bodies, and original rendered PDF pages for selected visual evidence. Frontmatter, workflow contamination, and wikilinks are checked deterministically. Reconciliation can prepare a validated change set, but there is still no vault-apply stage.

The `review` command refuses to overwrite an existing `agent_b/` result. Archive or rename that folder before intentionally rerunning the review.

## Reconciliation and human review

After Agent B has reviewed a staged run, generate the reconciled change set:

```bash
python -m sb_processor reconcile --run staging/run_<id> --vault ../gd-gdb
```

The command applies only allow-listed objective corrections and exact, single-span semantic removals or replacements. Ambiguous issues become narrow machine-readable decisions. It writes only under `<run>/reconciliation/`:

```text
HUMAN_REVIEW.md
human_decisions.json
reconciliation.json
final_change_set.json
WRITE_PREVIEW.md
diffs/
```

The normal workflow is:

1. Open `HUMAN_REVIEW.md`.
2. Put selected option keys in a separate JSON object, for example `{"HR-001": "DEFER"}`.
3. Rerun with `--decisions decisions.json`.
4. Inspect `WRITE_PREVIEW.md` and its UPDATE diffs.

`PENDING_HUMAN_REVIEW` means at least one blocking choice remains. `READY_FOR_WRITE` means only that the applicable subset passes the mandatory identity, dependency, path, frontmatter, conflict, and content-preservation gates; it does **not** authorize a write or mean any vault file was changed. `INVALID` means an included change failed a structural/content validator or conflict gate. Skipped, deferred, and blocked changes remain explicit and are excluded from the future write set. Reconciliation always starts from the preserved Agent A and Agent B artifacts, verifies their hashes while staging output, and never writes to the vault.

`HUMAN_REVIEW.md` lists only pending root decisions, every affected note, evidence, and the exact consequence of each offered option. `WRITE_PREVIEW.md` separates `CREATE`, `UPDATE`, `UNCHANGED`, `SKIPPED`, `DEFERRED`, `BLOCKED`, and `INVALID`; it also exposes accepted risks, blocking issues, and batch dependencies. Material existing-content removal requires `ACKNOWLEDGE_CONTENT_LOSS` and remains visible as an accepted risk. For an unresolved exact wikilink, `REMOVE_LINK` removes only the `[[...]]` markup and preserves its visible text; it never invents a replacement target. The [v1 evaluation](docs/reconciliation-v1-evaluation.md) records the original frozen-fixture lifecycle.

## PDF ingestion and extractor comparison

Inspect extraction and visual-page detection without generating a note proposal:

```bash
python -m sb_processor ingest-pdf --source /path/to/lecture.pdf --vault ../gd-gdb
python -m sb_processor compare-pdf --source /path/to/lecture.pdf --vault ../gd-gdb
python -m sb_processor compare-pdf --source /path/to/lecture.pdf --vault ../gd-gdb --include-docling
```

`ingest-pdf` uses the visual model only for flagged pages. With no API key or with `--skip-visual`, those pages stay unresolved. `compare-pdf` uses no API key; it compares PyMuPDF, AnyDoc, and PyMuPDF4LLM locally, with optional Docling. Use `--pdf-extractor anydoc`, `pymupdf4llm`, or `docling` with `ingest-pdf` or `process` after installing the corresponding extra.

The extractor returns numbered pages with raw text, positioned blocks where available, and image/drawing coverage metadata. The deterministic cleaner removes repeated edge-position headers/footers and page counters, suppresses later near-duplicate navigation pages, consolidates contiguous running section labels, normalizes known ligatures and whitespace artefacts, and joins clear wraps within text blocks. Each transformation has an auditable action in the structured document. Original PDF text and page numbers remain intact. AnyDoc single-page failures fall back to raw PyMuPDF for that page and are recorded in metadata.

Pages with little extracted text and substantial image or vector coverage receive `requires_visual_processing` and `visual_flags`. `ingest-pdf` renders only those pages and asks an OpenAI vision model to extract additional visible relationships. It stores raw text, cleaned text, and visual descriptions separately under `staging/ingestion/ingest_<id>/` as `document.json`, `text_raw.md`, `text_clean.md`, `agent_context.md`, and `summary.json`. The default visual model is `gpt-5.4`, chosen after the benchmark's nested-oval diagram was misread by smaller models; set `--visual-model` to change it. The model receives one page rendered at 2× and local context. Successful results are cached in `.data/visual_cache` using the source hash, rendered page hash, and model/prompt identity. Output and cache locations must be outside the vault.

The document's `completeness` object reports `COMPLETE` or `PARTIAL`, flagged pages, processed pages, and unresolved pages. A failed, empty, or ambiguous visual response remains unresolved. If the API key is unavailable or `--skip-visual` is set, flagged pages remain `PENDING`. `process` stops before the proposal call on a partial source. To proceed deliberately, pass `--allow-incomplete-visuals`; the staged proposal retains `PARTIAL` and lists unresolved pages for review. The source context preserves original page numbers and labels text and visual content separately. No specialized table fallback runs.

`compare-pdf` runs the three established backends locally without an API key, plus Docling when requested. Each run saves `<extractor>_raw.md`, `<extractor>_clean.md`, `<extractor>_document.json`, `comparison.json`, `comparison.md`, and `cleaning_report.md`. The JSON retains raw page text, block positions, section ranges, visual features, and cleaning decisions; `anydoc_whole_document.md` preserves the prior whole-document conversion separately because it cannot reliably identify source pages. It also records extraction time and Docling's native item counts. Character/word savings are measured, while token counts use a rough characters/4 estimate. Inspect representative slides: headings, reading order, tables, diagrams, equations, and bibliography can differ even when word counts look similar. `--vault` is required so output cannot be placed inside the vault.

Docling exports page-filtered Markdown and positioned text/table items. The adapter keeps its table Markdown and per-page picture counts, while the existing PyMuPDF visual features continue to drive the completeness gate. A detected picture is **not** treated as a visual interpretation or a resolved visual page. This adapter disables OCR, picture description, chart extraction, and remote services; it sends no document content to a cloud model. Docling's local models can consume considerable disk, memory, and CPU time. PyMuPDF remains the default pending evidence across more PDFs.

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

## Agent B v1.1 review

Run `sb-processor review --run <staged-run> --vault <matching-vault>` after Agent A staging. Agent B loads the canonical university review document from the vault to verify its presence, then sends the compact operational checklist under `src/sb_processor/prompts/` for each change. Every response must cover the note-type-specific Pydantic checklist. Deterministic metadata, provenance, contamination, naming, and link checks run alongside semantic review. A final batch call receives summaries and individual findings, without the complete source document.

Open `SUMMARY.md` first. `agent_b/detailed_report.md` contains all findings, while `agent_b/review.json`, `agent_b/requests/`, `agent_b/batch_request.json`, and `agent_b/diagnostics.json` preserve the structured audit. Agent B copies the original Agent A proposal and report under `agent_a/`; it keeps the original top-level `proposal.json` for the existing staging contract. Proposed corrections remain separate from Agent A drafts. Review never writes to the vault.

The [protocol mapping](docs/agent_b_protocol_mapping.md) connects each checklist category to the canonical Markdown sections. The [v1.1 evaluation](docs/agent-b-v1.1-evaluation.md) records the exact replay, context size, findings, and freeze decision.

## What the code checks

The registry supports normalized exact title, filename, alias, path, and note-type queries, plus lexical candidate search. Retrieval returns possible notes, never a semantic-equivalence decision. A `CREATE` with an exact/alias/normalized-variant collision or an existing target becomes `REVIEW_REQUIRED`; loose lexical and semantic overlap stays visible without automatically blocking creation. An `UPDATE` becomes `REVIEW_REQUIRED` if its target does not exist or its full current body was not sent to the model. An ambiguous concept resolution, conflicting existing path, or broad alias pointing to a narrower existing title also requires review. Unsafe paths, paths outside workflow roots, duplicate targets, and missing Markdown content require review. With an explicit incomplete-visual override, proposed writes become `REVIEW_REQUIRED`. Unresolved wikilinks are reported, not blocked. All proposals remain staged only.

All four text extractors run locally and accept text-based PDFs. The `anydoc` path explicitly uses `ocr="reject"`; it never invokes anydoc's hosted OCR, which would send a PDF to Firecrawl. Image-only PDFs need OCR before this PoC can process them. Visual enrichment sends only detector-flagged page images to the configured OpenAI API. Sources over 120,000 cleaned source characters are rejected instead of silently truncated. There is no web app or vault write operation.

## Tests

```bash
python -m pytest -q
```

Tests cover scanning/frontmatter, policy-aware metadata retrieval, alias and filename ranking, context size bounds, safe staging, update checks, PDF extractors, comparison output, completeness gating, selective rendering, caching, failures, and both OpenAI request shapes. They use fake clients for deterministic integration; a live Agent A run requires a PDF and `OPENAI_API_KEY`.

After the local model has been cached, run the actual multilingual retrieval test without cloud access with `SB_RUN_LOCAL_MODEL_TEST=1 python -m pytest -q`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the file map, schemas, SQLite tables, and design choices. The [ingestion v1 technical debt list](docs/technical-debt/ingestion-v1.md) records known follow-up work for Agent A and PDF ingestion.
