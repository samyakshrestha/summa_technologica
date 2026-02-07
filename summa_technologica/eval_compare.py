from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable

from .config import Settings
from .eval_v1 import (
    BenchmarkCase,
    create_run_dir,
    filter_cases,
    load_benchmarks,
    safe_slug,
    utc_now,
    write_json,
    write_text,
)
from .models import SummaResponse
from .v2_contracts import ContractValidationError, validate_v2_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summa-benchmark-compare",
        description="Run benchmark comparison between V1 and V2 and emit analysis reports.",
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
        default=Path("eval/results/compare"),
        help="Directory where run artifacts are stored.",
    )
    parser.add_argument(
        "--domain",
        action="append",
        default=[],
        help="Optional domain filter. Repeat for multiple domains.",
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
        help="Optional objective for both V1 and V2 runs.",
    )
    parser.add_argument(
        "--top",
        type=int,
        choices=[1, 3],
        default=1,
        help="V2 Summa rendering count (top 1 or top 3).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between cases to reduce throttling.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Optional label appended to run directory name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate benchmark selection and exit.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first case where both modes fail.",
    )
    parser.add_argument(
        "--skip-v1",
        action="store_true",
        help="Skip V1 execution.",
    )
    parser.add_argument(
        "--skip-v2",
        action="store_true",
        help="Skip V2 execution.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.skip_v1 and args.skip_v2:
        print("Error: cannot skip both v1 and v2.", file=sys.stderr)
        raise SystemExit(2)

    try:
        cases = load_benchmarks(args.benchmarks)
        selected = filter_cases(cases, domains=args.domain, limit=args.limit)
    except Exception as exc:
        print(f"Error loading benchmarks: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not selected:
        print("No benchmark cases selected.", file=sys.stderr)
        raise SystemExit(2)

    print(f"Loaded {len(cases)} benchmarks; selected {len(selected)}.")
    if args.dry_run:
        print("Dry run complete.")
        return

    try:
        run_v1 = None if args.skip_v1 else _load_v1_runner()
        run_v2 = None if args.skip_v2 else _load_v2_runner()
    except Exception as exc:
        print(f"Error loading runners: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    settings = Settings.from_env()
    run_dir = create_run_dir(args.output_root, args.run_label)
    manifest = {
        "started_at_utc": utc_now(),
        "benchmark_file": str(args.benchmarks),
        "selected_case_ids": [case.id for case in selected],
        "objective": args.objective,
        "domains_filter": args.domain,
        "top": args.top,
        "sleep_seconds": args.sleep_seconds,
        "model": settings.model,
        "skip_v1": args.skip_v1,
        "skip_v2": args.skip_v2,
    }
    write_json(run_dir / "manifest.json", manifest)

    records: list[dict[str, Any]] = []
    for index, case in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {case.id} ({case.domain})")
        record = run_case_pair(
            case=case,
            run_v1=run_v1,
            run_v2=run_v2,
            objective=args.objective,
            top=args.top,
        )
        records.append(record)
        write_json(run_dir / f"{index:02d}_{safe_slug(case.id)}.json", record)

        v1_status = record.get("v1", {}).get("status", "skipped")
        v2_status = record.get("v2", {}).get("status", "skipped")
        print(f"  -> v1={v1_status} | v2={v2_status}")

        if args.fail_fast and v1_status != "ok" and v2_status != "ok":
            print("Fail-fast triggered: both modes failed on this case.", file=sys.stderr)
            break

        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    summary = build_comparison_summary(
        records=records,
        manifest=manifest,
        finished_at_utc=utc_now(),
        model=settings.model,
    )
    write_json(run_dir / "summary.json", summary)
    write_text(run_dir / "summary.md", build_summary_markdown(summary))
    write_json(run_dir / "go_no_go.json", summary["go_no_go"])

    print(
        f"Comparison complete. Artifacts: {run_dir}\n"
        f"Go/No-Go: {summary['go_no_go']['recommendation']}"
    )


def run_case_pair(
    *,
    case: BenchmarkCase,
    run_v1: Callable[..., Any] | None,
    run_v2: Callable[..., Any] | None,
    objective: str | None,
    top: int,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "benchmark": asdict(case),
    }
    if run_v1 is not None:
        record["v1"] = run_case_v1(case=case, run_v1=run_v1, objective=objective)
    else:
        record["v1"] = {"status": "skipped"}

    if run_v2 is not None:
        record["v2"] = run_case_v2(case=case, run_v2=run_v2, objective=objective, top=top)
    else:
        record["v2"] = {"status": "skipped"}
    return record


def run_case_v1(
    *,
    case: BenchmarkCase,
    run_v1: Callable[..., SummaResponse],
    objective: str | None,
) -> dict[str, Any]:
    started = utc_now()
    t0 = time.perf_counter()
    try:
        result = run_v1(case.question, domain=case.domain, objective=objective)
        payload = result.to_dict()
        metrics = evaluate_v1_metrics(case=case, payload=payload)
        return {
            "status": "ok",
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "output": payload,
            "metrics": metrics,
        }
    except Exception as exc:
        return {
            "status": "error",
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def run_case_v2(
    *,
    case: BenchmarkCase,
    run_v2: Callable[..., dict[str, Any]],
    objective: str | None,
    top: int,
) -> dict[str, Any]:
    started = utc_now()
    t0 = time.perf_counter()
    try:
        payload = run_v2(case.question, domain=case.domain, objective=objective, top=top)
        metrics = evaluate_v2_metrics(case=case, payload=payload)
        return {
            "status": "ok",
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "output": payload,
            "metrics": metrics,
        }
    except Exception as exc:
        return {
            "status": "error",
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def evaluate_v1_metrics(case: BenchmarkCase, payload: dict[str, Any]) -> dict[str, Any]:
    text_blob = json.dumps(payload, ensure_ascii=False).lower()
    return {
        "summa_complete": is_summa_complete_v1(payload),
        "keyword_relevance": has_keyword_relevance(text_blob, case.relevance_keywords),
        "avoids_known_bad_pattern": avoids_bad_pattern(text_blob, case.known_bad_pattern),
    }


def evaluate_v2_metrics(case: BenchmarkCase, payload: dict[str, Any]) -> dict[str, Any]:
    schema_valid = True
    schema_error = ""
    try:
        validate_v2_payload(payload)
    except ContractValidationError as exc:
        schema_valid = False
        schema_error = str(exc)

    hypotheses = payload.get("hypotheses", []) if isinstance(payload, dict) else []
    total_citations = 0
    grounded_ids_or_dois = 0
    has_falsifiable = True
    for hypothesis in hypotheses if isinstance(hypotheses, list) else []:
        if not isinstance(hypothesis, dict):
            has_falsifiable = False
            continue
        preds = hypothesis.get("falsifiable_predictions")
        if not isinstance(preds, list) or not preds:
            has_falsifiable = False

        citations = hypothesis.get("citations")
        if isinstance(citations, list):
            total_citations += len(citations)
            for citation in citations:
                if isinstance(citation, dict):
                    if _has_nonempty_str(citation, "paper_id") or _has_nonempty_str(citation, "doi"):
                        grounded_ids_or_dois += 1
        else:
            has_falsifiable = False

    rendering = payload.get("summa_rendering", "")
    rendering_text = rendering if isinstance(rendering, str) else ""
    rendering_lower = rendering_text.lower()
    fallback_no_citations = "no grounded citations found" in rendering_lower
    text_blob = json.dumps(payload, ensure_ascii=False).lower()

    return {
        "schema_valid": schema_valid,
        "schema_error": schema_error,
        "summa_complete": is_summa_complete_text(rendering_text),
        "falsifiable_predictions_present": bool(has_falsifiable and hypotheses),
        "total_citations": total_citations,
        "grounded_citations_present": grounded_ids_or_dois >= 3 or fallback_no_citations,
        "keyword_relevance": has_keyword_relevance(text_blob, case.relevance_keywords),
        "avoids_known_bad_pattern": avoids_bad_pattern(text_blob, case.known_bad_pattern),
    }


def build_comparison_summary(
    *,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    finished_at_utc: str,
    model: str,
) -> dict[str, Any]:
    v1_stats = summarize_mode(records, "v1")
    v2_stats = summarize_mode(records, "v2")
    go_no_go = evaluate_go_no_go(v2_stats=v2_stats, model=model)

    return {
        "manifest": manifest,
        "finished_at_utc": finished_at_utc,
        "total_cases": len(records),
        "v1": v1_stats,
        "v2": v2_stats,
        "go_no_go": go_no_go,
        "cases": records,
    }


def summarize_mode(records: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    entries = [item.get(mode, {}) for item in records if isinstance(item.get(mode), dict)]
    ok_entries = [item for item in entries if item.get("status") == "ok"]
    error_entries = [item for item in entries if item.get("status") == "error"]
    skipped_entries = [item for item in entries if item.get("status") == "skipped"]

    durations = [float(item.get("duration_seconds", 0.0)) for item in ok_entries]
    avg_duration = round(statistics.mean(durations), 3) if durations else None
    p95_duration = round(_percentile(durations, 95), 3) if durations else None

    metrics: dict[str, Any] = {}
    if mode == "v1":
        metrics = {
            "summa_complete_rate": _rate(ok_entries, "summa_complete"),
            "keyword_relevance_rate": _rate(ok_entries, "keyword_relevance"),
            "avoids_known_bad_pattern_rate": _rate(ok_entries, "avoids_known_bad_pattern"),
        }
    elif mode == "v2":
        metrics = {
            "schema_valid_rate": _rate(ok_entries, "schema_valid"),
            "summa_complete_rate": _rate(ok_entries, "summa_complete"),
            "falsifiable_predictions_rate": _rate(ok_entries, "falsifiable_predictions_present"),
            "grounded_citations_rate": _rate(ok_entries, "grounded_citations_present"),
            "keyword_relevance_rate": _rate(ok_entries, "keyword_relevance"),
            "avoids_known_bad_pattern_rate": _rate(ok_entries, "avoids_known_bad_pattern"),
        }

    return {
        "total": len(entries),
        "succeeded": len(ok_entries),
        "failed": len(error_entries),
        "skipped": len(skipped_entries),
        "average_duration_seconds": avg_duration,
        "p95_duration_seconds": p95_duration,
        "metrics": metrics,
    }


def evaluate_go_no_go(*, v2_stats: dict[str, Any], model: str) -> dict[str, Any]:
    metrics = v2_stats.get("metrics", {})
    avg_duration = v2_stats.get("average_duration_seconds")
    p95_duration = v2_stats.get("p95_duration_seconds")

    checks = {
        "schema_valid_rate_ge_0_95": _threshold(metrics.get("schema_valid_rate"), 0.95),
        "falsifiable_predictions_rate_ge_0_90": _threshold(
            metrics.get("falsifiable_predictions_rate"), 0.90
        ),
        "grounded_citations_rate_ge_0_80": _threshold(
            metrics.get("grounded_citations_rate"), 0.80
        ),
        "summa_complete_rate_ge_0_95": _threshold(metrics.get("summa_complete_rate"), 0.95),
        "avg_duration_le_300s": _upper_bound(avg_duration, 300.0),
        "p95_duration_le_300s": _upper_bound(p95_duration, 300.0),
    }

    # Cost ceilings cannot be measured exactly without provider token telemetry.
    checks["cost_budget_requires_manual_review"] = None

    passed = all(value is True for key, value in checks.items() if value is not None)
    recommendation = "GO" if passed else "NO_GO"

    return {
        "recommendation": recommendation,
        "checks": checks,
        "notes": [
            f"Model evaluated: {model}",
            "Human novelty/testability rubric delta still requires manual scoring.",
            "Cost ceiling check requires provider token telemetry integration.",
        ],
    }


def build_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# V1 vs V2 Benchmark Comparison")
    lines.append("")
    lines.append(f"- Total cases: {summary['total_cases']}")
    lines.append(f"- Recommendation: {summary['go_no_go']['recommendation']}")
    lines.append("")

    lines.append("## Mode Summary")
    lines.append("")
    lines.append("| Mode | Succeeded | Failed | Avg Duration (s) | P95 Duration (s) |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for mode in ["v1", "v2"]:
        stats = summary[mode]
        lines.append(
            f"| {mode} | {stats['succeeded']} | {stats['failed']} | "
            f"{stats['average_duration_seconds']} | {stats['p95_duration_seconds']} |"
        )
    lines.append("")

    lines.append("## V2 Checks")
    lines.append("")
    for name, value in summary["go_no_go"]["checks"].items():
        lines.append(f"- {name}: {value}")
    lines.append("")

    lines.append("## Case Table")
    lines.append("")
    lines.append("| ID | Domain | V1 | V2 | V1 Duration | V2 Duration |")
    lines.append("| --- | --- | --- | --- | ---: | ---: |")
    for item in summary["cases"]:
        bench = item["benchmark"]
        v1 = item.get("v1", {})
        v2 = item.get("v2", {})
        lines.append(
            f"| {bench['id']} | {bench['domain']} | {v1.get('status')} | {v2.get('status')} | "
            f"{v1.get('duration_seconds')} | {v2.get('duration_seconds')} |"
        )

    lines.append("")
    lines.append("## Notes")
    for note in summary["go_no_go"]["notes"]:
        lines.append(f"- {note}")

    lines.append("")
    return "\n".join(lines)


def is_summa_complete_v1(payload: dict[str, Any]) -> bool:
    objections = payload.get("objections")
    replies = payload.get("replies")
    return (
        isinstance(payload.get("question"), str)
        and isinstance(payload.get("on_the_contrary"), str)
        and isinstance(payload.get("i_answer_that"), str)
        and isinstance(objections, list)
        and len(objections) == 3
        and isinstance(replies, list)
        and len(replies) == 3
    )


def is_summa_complete_text(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    lowered = text.lower()
    required = [
        "question:",
        "objections:",
        "on the contrary",
        "i answer that",
        "replies to objections",
    ]
    if any(marker not in lowered for marker in required):
        return False
    return all(f"{n}." in text for n in [1, 2, 3])


def has_keyword_relevance(text_blob: str, keywords: list[str]) -> bool:
    lowered = text_blob.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def avoids_bad_pattern(text_blob: str, bad_pattern: str) -> bool:
    return bad_pattern.lower() not in text_blob.lower()


def _has_nonempty_str(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    return isinstance(value, str) and bool(value.strip())


def _rate(entries: list[dict[str, Any]], metric_key: str) -> float | None:
    if not entries:
        return None
    true_count = 0
    for item in entries:
        metrics = item.get("metrics")
        if isinstance(metrics, dict) and metrics.get(metric_key) is True:
            true_count += 1
    return round(true_count / len(entries), 3)


def _threshold(value: float | None, threshold: float) -> bool | None:
    if value is None:
        return None
    return value >= threshold


def _upper_bound(value: float | None, threshold: float) -> bool | None:
    if value is None:
        return None
    return value <= threshold


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if percentile <= 0:
        return min(values)
    if percentile >= 100:
        return max(values)
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * (percentile / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _load_v1_runner() -> Callable[..., SummaResponse]:
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


def _load_v2_runner() -> Callable[..., dict[str, Any]]:
    try:
        from .crew_v2 import run_summa_v2
    except ModuleNotFoundError as exc:
        if exc.name == "crewai":
            raise RuntimeError(
                "crewai is not installed in this environment. "
                "Run: pip install crewai && pip install -e ."
            ) from exc
        raise
    return run_summa_v2


if __name__ == "__main__":
    main()

