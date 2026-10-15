"""CLI entry point for bulk company LinkedIn search, scraping, and corpus ingest.

Usage:
    # Resolve and preview LinkedIn company URLs only (no scrape cost):
    python -m processors.run_company_collection --companies "Stripe, OpenAI, Databricks" --dry-run

    # Scrape 10 most recent posts from each company and ingest into corpus:
    python -m processors.run_company_collection --companies "Stripe, OpenAI" --max-posts 10

    # Bulk input from a file (one company name or URL per line):
    python -m processors.run_company_collection --file companies.txt --max-posts 10 --with-gemini
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config.settings import load_settings
from processors.company_collector import (
    parse_bulk_company_input,
    resolve_company_urls,
    run_company_corpus_flow,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search company names, scrape 10 recent LinkedIn posts, and ingest into pgvector corpus."
    )
    parser.add_argument(
        "--companies",
        type=str,
        default="",
        help="Comma-separated or newline-separated company names or LinkedIn URLs.",
    )
    parser.add_argument(
        "--file",
        type=str,
        default="",
        help="Path to a text file with one company name or URL per line.",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=10,
        help="Number of most recent posts to scrape per company (default: 10).",
    )
    parser.add_argument(
        "--with-gemini",
        action="store_true",
        help="Run Stage 2 Gemini qualitative feature analysis on scraped posts.",
    )
    parser.add_argument(
        "--dry-run",
        "--resolve-only",
        dest="dry_run",
        action="store_true",
        help="Only resolve and display company LinkedIn URLs without scraping or ingesting.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    raw_inputs: list[str] = []

    if args.companies:
        raw_inputs.extend(args.companies.splitlines() if "\n" in args.companies else args.companies.split(","))

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"Error: Company list file not found: {args.file}", file=sys.stderr)
            return 1
        raw_inputs.extend(file_path.read_text().splitlines())

    companies = parse_bulk_company_input(raw_inputs)
    if not companies:
        print("Error: No company names or URLs provided. Use --companies or --file.", file=sys.stderr)
        return 1

    settings = load_settings()
    print(f"Processing {len(companies)} company input(s)...")

    if args.dry_run:
        print("\nResolving company LinkedIn URLs (Dry Run)...")
        resolved = resolve_company_urls(companies, settings)
        print("-" * 75)
        for item in resolved:
            status_symbol = "✓" if item.status in ("resolved", "provided_url") else "✗"
            print(f" {status_symbol} [{item.input_text}] -> {item.linkedin_url} ({item.notes})")
        print("-" * 75)
        print(f"Resolved {sum(1 for i in resolved if i.linkedin_url)}/{len(resolved)} company URLs successfully.")
        return 0

    print(f"\nStarting bulk company scrape (up to {args.max_posts} posts each) & corpus ingestion...")
    result = run_company_corpus_flow(
        companies,
        max_posts_per_company=args.max_posts,
        settings=settings,
        with_gemini=args.with_gemini,
        on_progress=lambda msg: print(f"[*] {msg}"),
    )

    print("\n" + "=" * 75)
    if result.status == "success":
        print(f" SUCCESS: Ingested {result.total_posts_ingested} post(s) into the Postgres vector corpus.")
        if result.raw_file_path:
            print(f" Raw JSON:    {result.raw_file_path}")
        if result.analysed_jsonl:
            print(f" Analysed:    {result.analysed_jsonl}")
        if result.embeddings_path:
            print(f" Embeddings:  {result.embeddings_path}")
        if result.apify_cost_usd:
            print(f" Apify spend: ${result.apify_cost_usd:.4f}")
        return 0
    else:
        print(f" FAILED / PARTIAL: Status = {result.status}")
        for err in result.errors:
            print(f" - {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
