from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import Settings
from .formatter import to_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summa-technologica",
        description="Generate a Summa-style structured response to a question.",
    )
    parser.add_argument("question", nargs="?", help="The idea or question to analyze.")
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
        "--save",
        type=Path,
        help="Optional path to save output.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()

    question = args.question or input("Enter your idea/question: ").strip()
    if not question:
        print("Error: question is required.", file=sys.stderr)
        raise SystemExit(2)

    try:
        from .crew import run_summa
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
        result = run_summa(question, domain=domain, objective=objective)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    text = result.to_json() if args.format == "json" else to_markdown(result)
    if args.save:
        args.save.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
