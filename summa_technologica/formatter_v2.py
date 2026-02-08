"""Core utilities for formatter v2 in Summa Technologica."""

from __future__ import annotations

from typing import Any


def to_markdown_v2(payload: dict[str, Any]) -> str:
    """To markdown v2."""
    lines: list[str] = []
    lines.append(f"Question: {payload.get('question', '')}")
    lines.append(f"Domain: {payload.get('domain', '')}")
    lines.append("")

    hypotheses = payload.get("hypotheses", [])
    ranked = payload.get("ranked_hypothesis_ids", [])
    if isinstance(hypotheses, list) and isinstance(ranked, list):
        by_id = {
            item.get("id"): item
            for item in hypotheses
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if ranked:
            lines.append("Ranked hypotheses:")
            for idx, hypothesis_id in enumerate(ranked, start=1):
                hypothesis = by_id.get(hypothesis_id, {})
                title = hypothesis.get("title", "")
                scores = hypothesis.get("scores", {}) if isinstance(hypothesis, dict) else {}
                overall = scores.get("overall") if isinstance(scores, dict) else None
                lines.append(f"{idx}. {hypothesis_id} - {title} (overall={overall})")
            lines.append("")

    summa_rendering = payload.get("summa_rendering")
    if isinstance(summa_rendering, str) and summa_rendering.strip():
        lines.append(summa_rendering.strip())
    else:
        lines.append("No Summa rendering produced.")

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        lines.append("")
        lines.append("Pipeline error:")
        stage = error_payload.get("stage", "unknown")
        message = error_payload.get("message", "")
        retry = error_payload.get("retry_attempted")
        lines.append(f"- stage: {stage}")
        lines.append(f"- message: {message}")
        lines.append(f"- retry_attempted: {retry}")

    return "\n".join(lines).strip() + "\n"

