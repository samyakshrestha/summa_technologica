"""Schema validation — ensures the final pipeline output is well-formed.

Before the pipeline returns its result, this file checks that the output
matches the JSON schema (schemas/hypothesis_schema.json). It validates:
  - Required fields exist (question, domain, hypotheses, ranked_hypothesis_ids)
  - Hypothesis IDs are unique and match the ranking list
  - Each hypothesis has exactly 3 objections and 3 replies (numbered 1,2,3)
  - Pairwise comparisons reference valid hypothesis IDs
  - Score formula is consistent (35% novelty + 30% plausibility + 35% testability)
  - Citations are grounded in the Semantic Scholar retrieval results

If validation fails, the pipeline either retries the Summa Composer or
returns a partial-failure payload with diagnostic info.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .semantic_scholar import (
    SemanticScholarPaper,
    validate_citations_against_papers,
)


class ContractValidationError(ValueError):
    """Raised when a V2 payload violates schema or contract rules."""


@dataclass(frozen=True)
class PipelineErrorContract:
    stage: str
    message: str
    retry_attempted: bool

    def to_dict(self) -> dict[str, Any]:
        """To dict."""
        return {
            "stage": self.stage,
            "message": self.message,
            "retry_attempted": self.retry_attempted,
        }


def resolve_v2_schema_path(schema_path: Path | None = None) -> Path:
    """Resolve v2 schema path."""
    if schema_path is not None:
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        return schema_path

    candidates = [
        Path(__file__).resolve().parents[1] / "schemas" / "hypothesis_schema.json",
        Path.cwd() / "schemas" / "hypothesis_schema.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Could not locate V2 schema file. Expected one of: "
        + ", ".join(str(path) for path in candidates)
    )


def load_v2_schema(schema_path: Path | None = None) -> dict[str, Any]:
    """Load v2 schema."""
    path = resolve_v2_schema_path(schema_path)
    content = path.read_text(encoding="utf-8")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ContractValidationError("V2 schema must be a top-level JSON object.")
    return parsed


def parse_and_validate_v2_json(
    raw: str,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Parse and validate v2 json."""
    payload = _extract_json_object(raw)
    return validate_v2_payload(payload, schema_path=schema_path)


def validate_v2_payload(
    payload: dict[str, Any],
    schema_path: Path | None = None,
    grounded_papers: list[SemanticScholarPaper] | None = None,
) -> dict[str, Any]:
    """Validate v2 payload."""
    if not isinstance(payload, dict):
        raise ContractValidationError("V2 payload must be a JSON object.")

    schema = load_v2_schema(schema_path)
    _validate_against_jsonschema(payload, schema)
    _validate_hypothesis_ids(payload)
    _validate_hypothesis_triplets(payload)
    _validate_pairwise_references(payload)
    _validate_score_formula(payload)
    if grounded_papers is not None:
        _validate_citation_grounding(payload, grounded_papers)
    return payload


def validate_partial_failure_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate terminal failure payload structure for retry-once failure mode."""
    if not isinstance(payload, dict):
        raise ContractValidationError("Partial failure payload must be an object.")

    _require_nonempty_str(payload, "question")
    _require_nonempty_str(payload, "domain")

    hypotheses = payload.get("hypotheses")
    ranked = payload.get("ranked_hypothesis_ids")
    stage_outputs = payload.get("stage_outputs")
    error_payload = payload.get("error")
    summa_rendering = payload.get("summa_rendering")

    if not isinstance(hypotheses, list):
        raise ContractValidationError("Field 'hypotheses' must be a list.")
    if not isinstance(ranked, list):
        raise ContractValidationError("Field 'ranked_hypothesis_ids' must be a list.")
    if not isinstance(stage_outputs, dict):
        raise ContractValidationError("Field 'stage_outputs' must be an object.")
    if not isinstance(summa_rendering, str):
        raise ContractValidationError("Field 'summa_rendering' must be a string.")
    if not isinstance(error_payload, dict):
        raise ContractValidationError("Field 'error' must be an object.")

    _require_nonempty_str(error_payload, "stage")
    _require_nonempty_str(error_payload, "message")
    retry_attempted = error_payload.get("retry_attempted")
    if not isinstance(retry_attempted, bool):
        raise ContractValidationError("Field 'error.retry_attempted' must be a boolean.")

    return payload


def build_partial_failure_payload(
    *,
    question: str,
    domain: str,
    error: PipelineErrorContract,
    stage_outputs: dict[str, Any] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    ranked_hypothesis_ids: list[str] | None = None,
    summa_rendering: str = "",
) -> dict[str, Any]:
    """Build partial failure payload."""
    payload = {
        "question": question,
        "domain": domain,
        "hypotheses": hypotheses or [],
        "ranked_hypothesis_ids": ranked_hypothesis_ids or [],
        "summa_rendering": summa_rendering,
        "stage_outputs": stage_outputs or {},
        "error": error.to_dict(),
    }
    return validate_partial_failure_payload(payload)


def _validate_against_jsonschema(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    """Internal helper to validate against jsonschema."""
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError as exc:
        raise ContractValidationError(
            "jsonschema is required for V2 contract validation. Install with: pip install -e ."
        ) from exc

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    details = []
    for err in errors[:5]:
        location = ".".join(str(item) for item in err.path) or "<root>"
        details.append(f"{location}: {err.message}")
    raise ContractValidationError("Schema validation failed: " + " | ".join(details))


def _validate_hypothesis_ids(payload: dict[str, Any]) -> None:
    """Internal helper to validate hypothesis ids."""
    hypotheses = payload["hypotheses"]
    hypothesis_ids: list[str] = []
    for hypothesis in hypotheses:
        hypothesis_id = hypothesis["id"]
        if hypothesis_id in hypothesis_ids:
            raise ContractValidationError(f"Duplicate hypothesis id found: {hypothesis_id}")
        hypothesis_ids.append(hypothesis_id)

    ranked = payload["ranked_hypothesis_ids"]
    hypothesis_id_set = set(hypothesis_ids)
    ranked_set = set(ranked)
    if ranked_set != hypothesis_id_set:
        raise ContractValidationError(
            "ranked_hypothesis_ids must contain exactly the hypothesis ids."
        )


def _validate_hypothesis_triplets(payload: dict[str, Any]) -> None:
    """Internal helper to validate hypothesis triplets."""
    expected_numbers = [1, 2, 3]
    for hypothesis in payload["hypotheses"]:
        objections = sorted(item["number"] for item in hypothesis["objections"])
        replies = sorted(item["objection_number"] for item in hypothesis["replies"])
        if objections != expected_numbers:
            raise ContractValidationError(
                f"Hypothesis {hypothesis['id']} objections must be numbered 1,2,3."
            )
        if replies != expected_numbers:
            raise ContractValidationError(
                f"Hypothesis {hypothesis['id']} replies must target objections 1,2,3."
            )


def _validate_pairwise_references(payload: dict[str, Any]) -> None:
    """Internal helper to validate pairwise references."""
    valid_ids = {item["id"] for item in payload["hypotheses"]}
    for hypothesis in payload["hypotheses"]:
        comparisons = hypothesis["pairwise_record"]["comparisons"]
        for comparison in comparisons:
            hypothesis_a = comparison["hypothesis_a_id"]
            hypothesis_b = comparison["hypothesis_b_id"]
            if hypothesis_a not in valid_ids or hypothesis_b not in valid_ids:
                raise ContractValidationError(
                    f"Hypothesis {hypothesis['id']} pairwise comparison references "
                    "unknown hypothesis ids."
                )
            if hypothesis_a == hypothesis_b:
                raise ContractValidationError(
                    f"Hypothesis {hypothesis['id']} pairwise comparison must involve two distinct ids."
                )


def _validate_score_formula(payload: dict[str, Any]) -> None:
    """Internal helper to validate score formula."""
    for hypothesis in payload["hypotheses"]:
        scores = hypothesis["scores"]
        expected = (
            0.35 * float(scores["novelty"])
            + 0.30 * float(scores["plausibility"])
            + 0.35 * float(scores["testability"])
        )
        if abs(float(scores["overall"]) - expected) > 0.06:
            raise ContractValidationError(
                f"Hypothesis {hypothesis['id']} has inconsistent overall score formula."
            )


def _validate_citation_grounding(
    payload: dict[str, Any],
    grounded_papers: list[SemanticScholarPaper],
) -> None:
    """Internal helper to validate citation grounding."""
    for hypothesis in payload["hypotheses"]:
        issues = validate_citations_against_papers(
            citations=hypothesis["citations"],
            papers=grounded_papers,
        )
        if issues:
            raise ContractValidationError(
                f"Hypothesis {hypothesis['id']} has invalid citation grounding: "
                + " | ".join(issues)
            )


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Internal helper to extract json object."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            snippet = raw[:220].replace("\n", " ")
            raise ContractValidationError(
                f"No JSON object found in model output: {snippet}"
            ) from None
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise ContractValidationError("Top-level JSON payload must be an object.")
    return data


def _require_nonempty_str(payload: dict[str, Any], key: str) -> str:
    """Internal helper to require nonempty str."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"Field '{key}' must be a non-empty string.")
    return value.strip()
