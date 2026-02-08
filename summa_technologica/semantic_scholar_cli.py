"""Core utilities for semantic scholar cli in Summa Technologica."""

from __future__ import annotations

import argparse
import json
import sys

from .config import Settings
from .semantic_scholar import retrieve_grounded_papers


def build_parser() -> argparse.ArgumentParser:
    """Build parser."""
    parser = argparse.ArgumentParser(
        prog="summa-semantic-search",
        description="Run dual-query Semantic Scholar retrieval and print structured JSON.",
    )
    parser.add_argument("question", help="Primary user question/query.")
    parser.add_argument(
        "--refined-query",
        default="",
        help="Optional refined query (for dual-query retrieval).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Per-query result limit (1-100).",
    )
    return parser


def main() -> None:
    """Run the main entrypoint for this module."""
    args = build_parser().parse_args()
    settings = Settings.from_env()

    try:
        result = retrieve_grounded_papers(
            question=args.question,
            refined_query=args.refined_query or None,
            base_url=settings.semantic_scholar_base_url,
            api_key=settings.semantic_scholar_api_key,
            per_query_limit=args.limit,
            timeout_seconds=settings.semantic_scholar_timeout_seconds,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()

