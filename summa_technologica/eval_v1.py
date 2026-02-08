"""Core utilities for eval v1 in Summa Technologica."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable

from .config import Settings


REQUIRED_DOMAINS = ("physics", "mathematics", "biology", "computer_science")


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    domain: str
    question: str
    relevance_keywords: list[str]
    known_bad_pattern: str


def build_parser() -> argparse.ArgumentParser:
    """Build parser."""
    parser = argparse.ArgumentParser(
        prog="summa-v1-benchmark",
        description="Run V1 benchmark suite and persist baseline outputs.",
    )
    parser.add_argument(
        "--benchmarks",
        type=Path,
        default=Path("eval/benchmarks.yaml"),
        help="Path to benchmark YAML file.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("eval/results/v1"),
        help="Directory where run artifacts are stored.",
    )
    parser.add_argument(
        "--domain",
        action="append",
        default=[],
        help="Optional domain filter. Repeat flag for multiple domains.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of selected benchmarks.",
    )
    parser.add_argument(
        "--objective",
        default=None,
        help="Optional objective passed to V1 runs.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Delay between calls to reduce provider throttling.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first failure.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate benchmark file and selection without calling the model.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Optional label appended to run directory name.",
    )
    return parser


def main() -> None:
    """Run the main entrypoint for this module."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        cases = load_benchmarks(args.benchmarks)
    except Exception as exc:
        print(f"Error loading benchmarks: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    selected = filter_cases(cases, domains=args.domain, limit=args.limit)
    if not selected:
        print("No benchmark cases selected after filtering.", file=sys.stderr)
        raise SystemExit(2)

    print(f"Loaded {len(cases)} benchmark cases; selected {len(selected)} for this run.")
    if args.dry_run:
        print("Dry run complete: benchmark definitions are valid.")
        return

    try:
        run_summa = _load_v1_runner()
    except Exception as exc:
        print(f"Error loading V1 runner: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    run_dir = create_run_dir(args.output_root, args.run_label)
    settings = Settings.from_env()
    run_started = utc_now()

    manifest = {
        "started_at_utc": run_started,
        "benchmark_file": str(args.benchmarks),
        "selected_case_ids": [case.id for case in selected],
        "objective": args.objective,
        "domains_filter": args.domain,
        "model": settings.model,
        "sleep_seconds": args.sleep_seconds,
    }
    write_json(run_dir / "manifest.json", manifest)

    records: list[dict[str, Any]] = []
    failures = 0

    for index, case in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] Running {case.id} ({case.domain})")
        record = run_case(case=case, run_summa=run_summa, objective=args.objective)
        records.append(record)

        case_file = run_dir / f"{index:02d}_{safe_slug(case.id)}.json"
        write_json(case_file, record)

        if record["status"] == "error":
            failures += 1
            print(f"  -> failed: {record['error']['message']}", file=sys.stderr)
            if args.fail_fast:
                print("Fail-fast enabled; stopping early.", file=sys.stderr)
                break
        else:
            print(f"  -> ok ({record['duration_seconds']}s)")

        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    summary = build_summary(
        records=records,
        manifest=manifest,
        finished_at_utc=utc_now(),
    )
    write_json(run_dir / "summary.json", summary)
    write_text(run_dir / "summary.md", build_summary_markdown(summary))

    print(
        f"Run complete. Success: {summary['succeeded']} | "
        f"Failed: {summary['failed']} | Artifacts: {run_dir}"
    )
    if failures:
        raise SystemExit(1)


def load_benchmarks(path: Path) -> list[BenchmarkCase]:
    """Load benchmarks."""
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required. Install dependencies with: pip install -e ."
        ) from exc

    if not path.exists():
        raise FileNotFoundError(f"Benchmark file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Benchmark YAML must be a list of benchmark items.")

    cases: list[BenchmarkCase] = []
    ids: set[str] = set()

    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Benchmark item #{idx} is not an object.")

        case_id = read_nonempty_str(item, "id", idx)
        domain = read_nonempty_str(item, "domain", idx).lower()
        question = read_nonempty_str(item, "question", idx)
        known_bad_pattern = read_nonempty_str(item, "known_bad_pattern", idx)
        keywords = read_keywords(item, idx)

        if case_id in ids:
            raise ValueError(f"Duplicate benchmark id: {case_id}")
        ids.add(case_id)

        cases.append(
            BenchmarkCase(
                id=case_id,
                domain=domain,
                question=question,
                relevance_keywords=keywords,
                known_bad_pattern=known_bad_pattern,
            )
        )

    validate_domain_coverage(cases)
    return cases


def filter_cases(
    cases: list[BenchmarkCase],
    domains: list[str],
    limit: int | None,
) -> list[BenchmarkCase]:
    """Filter cases."""
    filtered = cases
    if domains:
        allowed = {value.strip().lower() for value in domains if value.strip()}
        filtered = [case for case in filtered if case.domain in allowed]

    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be greater than zero.")
        filtered = filtered[:limit]

    return filtered


def run_case(
    case: BenchmarkCase,
    run_summa: Callable[..., Any],
    objective: str | None,
) -> dict[str, Any]:
    """Run case."""
    started_at = utc_now()
    t0 = time.perf_counter()

    try:
        result = run_summa(case.question, domain=case.domain, objective=objective)
        payload = {
            "status": "ok",
            "benchmark": asdict(case),
            "started_at_utc": started_at,
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "output": result.to_dict(),
        }
    except Exception as exc:
        payload = {
            "status": "error",
            "benchmark": asdict(case),
            "started_at_utc": started_at,
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }

    return payload


def build_summary(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    finished_at_utc: str,
) -> dict[str, Any]:
    """Build summary."""
    succeeded = [item for item in records if item["status"] == "ok"]
    failed = [item for item in records if item["status"] == "error"]
    avg_duration = (
        round(sum(item["duration_seconds"] for item in succeeded) / len(succeeded), 3)
        if succeeded
        else None
    )

    return {
        "manifest": manifest,
        "finished_at_utc": finished_at_utc,
        "total": len(records),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "average_duration_seconds_success": avg_duration,
        "cases": [
            {
                "id": item["benchmark"]["id"],
                "domain": item["benchmark"]["domain"],
                "status": item["status"],
                "duration_seconds": item["duration_seconds"],
                "error": item.get("error"),
            }
            for item in records
        ],
    }


def build_summary_markdown(summary: dict[str, Any]) -> str:
    """Build summary markdown."""
    lines: list[str] = []
    lines.append("# V1 Baseline Summary")
    lines.append("")
    lines.append(f"- Total: {summary['total']}")
    lines.append(f"- Succeeded: {summary['succeeded']}")
    lines.append(f"- Failed: {summary['failed']}")
    lines.append(
        "- Average duration (success): "
        f"{summary['average_duration_seconds_success']}"
    )
    lines.append("")
    lines.append("| ID | Domain | Status | Duration (s) | Error |")
    lines.append("| --- | --- | --- | ---: | --- |")

    for item in summary["cases"]:
        error_text = item["error"]["message"] if item["error"] else ""
        lines.append(
            f"| {item['id']} | {item['domain']} | {item['status']} | "
            f"{item['duration_seconds']} | {error_text} |"
        )

    return "\n".join(lines) + "\n"


def create_run_dir(output_root: Path, run_label: str | None) -> Path:
    """Create run dir."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = safe_slug(run_label) if run_label else ""
    dirname = f"{stamp}_{suffix}" if suffix else stamp

    run_dir = output_root / dirname
    if run_dir.exists():
        run_dir = output_root / f"{dirname}_1"

    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def safe_slug(value: str | None) -> str:
    """Safe slug."""
    if not value:
        return ""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return slug.strip("._-")


def read_nonempty_str(payload: dict[str, Any], key: str, idx: int) -> str:
    """Read nonempty str."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Benchmark item #{idx} field '{key}' must be a non-empty string.")
    return value.strip()


def read_keywords(payload: dict[str, Any], idx: int) -> list[str]:
    """Read keywords."""
    value = payload.get("relevance_keywords")
    if not isinstance(value, list) or not (1 <= len(value) <= 3):
        raise ValueError(
            f"Benchmark item #{idx} field 'relevance_keywords' must be a list with 1-3 items."
        )

    normalized: list[str] = []
    for keyword in value:
        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError(
                f"Benchmark item #{idx} has invalid keyword in 'relevance_keywords'."
            )
        normalized.append(keyword.strip())
    return normalized


def validate_domain_coverage(cases: list[BenchmarkCase]) -> None:
    """Validate domain coverage."""
    counts = {domain: 0 for domain in REQUIRED_DOMAINS}
    for case in cases:
        if case.domain in counts:
            counts[case.domain] += 1

    missing = [domain for domain, count in counts.items() if count < 5]
    if missing:
        raise ValueError(
            "Benchmark file must include at least 5 items for each required domain: "
            + ", ".join(missing)
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write json."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    """Write text."""
    path.write_text(text, encoding="utf-8")


def utc_now() -> str:
    """Utc now."""
    return datetime.now(timezone.utc).isoformat()


def _load_v1_runner() -> Callable[..., Any]:
    """Internal helper to load v1 runner."""
    try:
        from .crew import run_summa
    except ModuleNotFoundError as exc:
        if exc.name == "crewai":
            raise RuntimeError(
                "crewai is not installed in this environment. "
                "Run: pip install crewai && pip install -e ."
            ) from exc
        raise
    return run_summa


if __name__ == "__main__":
    main()

