"""Summa Technologica scaffold package."""

from .models import SummaResponse
from .v2_contracts import (
    ContractValidationError,
    PipelineErrorContract,
    build_partial_failure_payload,
    parse_and_validate_v2_json,
    validate_partial_failure_payload,
    validate_v2_payload,
)


def run_summa(*args, **kwargs):
    from .crew import run_summa as _run_summa

    return _run_summa(*args, **kwargs)


__all__ = [
    "run_summa",
    "SummaResponse",
    "ContractValidationError",
    "PipelineErrorContract",
    "build_partial_failure_payload",
    "parse_and_validate_v2_json",
    "validate_partial_failure_payload",
    "validate_v2_payload",
]
