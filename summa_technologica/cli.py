"""Core utilities for cli in Summa Technologica."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .config import Settings
from .formatter import to_markdown
from .formatter_v2 import to_markdown_v2


def build_parser() -> argparse.ArgumentParser:
    """Build parser."""
    parser = argparse.ArgumentParser(
        prog="summa-technologica",
        description="Generate a Summa-style structured response to a question.",
    )
    parser.add_argument("question", nargs="?", help="The idea or question to analyze.")
    parser.add_argument(
        "--mode",
        choices=["v1", "v2"],
        default="v1",
        help="v1: Summa-only argument mode. v2: hypothesis engine with retrieval/ranking.",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Domain focus (examples: physics, mathematics, economics).",
    )
    parser.add_argument(
        "--objective",
        default=None,
        help="Brainstorming objective for this run.",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--top",
        type=int,
        choices=[1, 3],
        default=1,
        help="In v2 mode, render top 1 or top 3 Summa blocks.",
    )
    parser.add_argument(
        "--save",
        type=Path,
        help="Optional path to save output.",
    )
    return parser


def main() -> None:
    """Run the main entrypoint for this module."""
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()

    question = args.question or input("Enter your idea/question: ").strip()
    if not question:
        print("Error: question is required.", file=sys.stderr)
        raise SystemExit(2)

    try:
        from .crew import run_summa
        from .crew_v2 import run_summa_v2
    except ModuleNotFoundError as exc:
        if exc.name == "crewai":
            print(
                "Error: crewai is not installed in this environment.\n"
                "Run the following from the project root:\n"
                "  pip install crewai\n"
                "  pip install -e .",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        raise

    domain = args.domain or settings.default_domain
    objective = args.objective or settings.default_objective

    try:
        if args.mode == "v2":
            result = run_summa_v2(
                question,
                domain=domain,
                objective=objective,
                top=args.top,
            )
        else:
            result = run_summa(question, domain=domain, objective=objective)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.mode == "v2":
        text = (
            json.dumps(result, indent=2, ensure_ascii=True)
            if args.format == "json"
            else to_markdown_v2(result)
        )
    else:
        text = result.to_json() if args.format == "json" else to_markdown(result)
    if args.save:
        args.save.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
