from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .llm import OpenAILLMClient
from .ingestion import ingest_pdf, stage_ingestion
from .pdf import compare_pdf_extractors
from .pipeline import process_source
from .registry import Registry
from .vault import scan_vault
from .workflows.university import UniversityWorkflow
from .visual import OpenAIVisualPageExtractor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb-processor", description="Read a vault and stage reviewed processing proposals")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Rebuild the disposable SQLite index")
    scan.add_argument("--vault", type=Path, required=True)
    scan.add_argument("--database", type=Path, default=Path(".data/registry.sqlite"))
    lookup = sub.add_parser("lookup", help="Find deterministic title, filename, alias, or lexical candidates")
    lookup.add_argument("query")
    lookup.add_argument("--database", type=Path, default=Path(".data/registry.sqlite"))
    process = sub.add_parser("process", help="Process one source and stage a proposal")
    process.add_argument("--workflow", choices=["university"], required=True)
    process.add_argument("--source", type=Path, required=True)
    process.add_argument("--vault", type=Path, required=True)
    process.add_argument("--staging", type=Path, default=Path("staging"))
    process.add_argument("--database", type=Path, default=Path(".data/registry.sqlite"))
    process.add_argument("--model", default="gpt-4o-mini")
    process.add_argument("--pdf-extractor", choices=["pymupdf", "anydoc", "pymupdf4llm"], default="pymupdf")
    process.add_argument("--visual-model", default="gpt-5.4")
    process.add_argument("--visual-cache", type=Path, default=Path(".data/visual_cache"))
    process.add_argument("--skip-visual", action="store_true", help="Leave detected visual pages unresolved")
    process.add_argument("--allow-incomplete-visuals", action="store_true")
    process.add_argument("--rules", type=Path)
    process.add_argument("--templates", type=Path)
    process.add_argument("--instructions", type=Path)
    compare = sub.add_parser("compare-pdf", help="Compare raw and cleaned PDF conversions without calling an LLM")
    compare.add_argument("--source", type=Path, required=True)
    compare.add_argument("--output-dir", type=Path, default=Path("staging/comparisons"))
    compare.add_argument("--vault", type=Path, required=True, help="Reject comparison output inside this vault")
    ingest = sub.add_parser("ingest-pdf", help="Extract, clean, and selectively enrich PDF pages without Agent A")
    ingest.add_argument("--source", type=Path, required=True)
    ingest.add_argument("--vault", type=Path, required=True, help="Reject ingestion artifacts inside this vault")
    ingest.add_argument("--output-dir", type=Path, default=Path("staging/ingestion"))
    ingest.add_argument("--visual-cache", type=Path, default=Path(".data/visual_cache"))
    ingest.add_argument("--visual-model", default="gpt-5.4")
    ingest.add_argument("--pdf-extractor", choices=["pymupdf", "anydoc", "pymupdf4llm"], default="pymupdf")
    ingest.add_argument("--skip-visual", action="store_true", help="Leave detected visual pages unresolved")
    return parser


def _visual_extractor(skip: bool, model: str):
    if skip or not os.environ.get("OPENAI_API_KEY"):
        return None
    return OpenAIVisualPageExtractor(model)


def _reject_inside_vault(parser: argparse.ArgumentParser, vault: Path, *paths: Path) -> None:
    root = vault.resolve(strict=True)
    if any(path.resolve().is_relative_to(root) for path in paths):
        parser.error("Output and cache paths must be outside the vault")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "scan":
        vault = args.vault.resolve(strict=True)
        database = args.database.resolve()
        if database.is_relative_to(vault):
            parser.error("Database must be outside the vault")
        count = Registry(database).rebuild(scan_vault(vault))
        print(f"Indexed {count} notes in {database}")
    elif args.command == "lookup":
        for match in Registry(args.database).lookup(args.query):
            print(f"{match.match_kind:14} {match.score:.2f} {match.path}")
    elif args.command == "process":
        _reject_inside_vault(parser, args.vault, args.staging, args.database, args.visual_cache)
        workflow = UniversityWorkflow(rules_path=args.rules, templates_path=args.templates, instructions_path=args.instructions,
                                      pdf_extractor=args.pdf_extractor, visual_extractor=_visual_extractor(args.skip_visual, args.visual_model),
                                      visual_cache=args.visual_cache)
        run = process_source(vault_path=args.vault, source_path=args.source, staging_path=args.staging, database_path=args.database,
                             workflow=workflow, llm=OpenAILLMClient(args.model),
                             allow_incomplete_visuals=args.allow_incomplete_visuals)
        print(f"Staged proposal: {run}")
    elif args.command == "compare-pdf":
        if args.output_dir.resolve().is_relative_to(args.vault.resolve(strict=True)):
            parser.error("Comparison output must be outside the vault")
        run = compare_pdf_extractors(args.source, args.output_dir)
        print(f"Saved comparison: {run}")
    elif args.command == "ingest-pdf":
        _reject_inside_vault(parser, args.vault, args.output_dir, args.visual_cache)
        extractor = _visual_extractor(args.skip_visual, args.visual_model)
        document, stats = ingest_pdf(args.source, args.pdf_extractor, visual_extractor=extractor,
                                     cache_dir=args.visual_cache)
        run = stage_ingestion(document, stats, args.output_dir)
        print(f"Saved ingestion: {run}")
        print(f"Completeness: {document.completeness.status.value}; unresolved visual pages: "
              f"{document.completeness.unprocessed_visual_pages}; visual calls: {stats.api_calls}; cache hits: {stats.cache_hits}")
    return 0
